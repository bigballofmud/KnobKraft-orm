#include "BCR2000FrontPanel.h"

#include "BCR2000.h"
#include "UIModel.h"

#include <spdlog/spdlog.h>

namespace {
	constexpr int kPollMs = 1000;
	constexpr int64 kUploadTimeoutMs = 3000;
	constexpr int kBclReply = 0x21;
}

BCR2000FrontPanel::BCR2000FrontPanel()
{
	startTimer(kPollMs);
}

BCR2000FrontPanel::~BCR2000FrontPanel()
{
	stopTimer();
	disconnect();
}

std::shared_ptr<midikraft::BCR2000> BCR2000FrontPanel::findBcr() const
{
	for (auto holder : UIModel::instance()->synthList_.allSynths()) {
		auto bcr = std::dynamic_pointer_cast<midikraft::BCR2000>(holder.synth());
		if (bcr && bcr->wasDetected() && !bcr->midiInput().identifier.isEmpty() && !bcr->midiOutput().identifier.isEmpty()) {
			return bcr;
		}
	}
	return nullptr;
}

void BCR2000FrontPanel::connect(std::shared_ptr<midikraft::BCR2000> const& bcr)
{
	disconnect();
	bcr_ = bcr;
	input_ = bcr->midiInput();
	auto controller = midikraft::MidiController::instance();
	controller->acquireMidiInput(input_);
	controller->enableMidiOutput(bcr->midiOutput());
	handler_ = midikraft::MidiController::makeOneHandle();
	WeakReference<BCR2000FrontPanel> self(this);
	auto input = input_;
	controller->addMessageHandler(handler_, [self, input](MidiInput* source, MidiMessage const& message) {
		if (!source || source->getDeviceInfo() != input) return;
		if (!message.isController() && !message.isSysEx()) return;
		MessageManager::callAsync([self, message]() {
			if (auto panel = self.get()) panel->handleMessage(message);
		});
	});
	presetLoaded_ = false;
	programmedPage_.clear();
	knobValues_.clear();
	spdlog::info("BCR2000 front panel connected on {}", input_.name.toStdString());
	programPage();
}

void BCR2000FrontPanel::disconnect()
{
	if (handler_ != midikraft::MidiController::makeNoneHandle()) {
		auto controller = midikraft::MidiController::instance();
		controller->removeMessageHandler(handler_);
		controller->releaseMidiInput(input_);
		handler_ = midikraft::MidiController::makeNoneHandle();
	}
	bcr_.reset();
	upload_.clear();
	uploadNext_ = 0;
}

void BCR2000FrontPanel::timerCallback()
{
	if (!upload_.empty() && Time::currentTimeMillis() - lastUploadActivity_ > kUploadTimeoutMs) {
		spdlog::warn("BCR2000 stopped answering while it was being set up as a front panel");
		finishUpload(false);
	}
	auto bcr = findBcr();
	if (bcr != bcr_.lock()) {
		if (bcr) {
			connect(bcr);
		}
		else {
			disconnect();
			if (onPageChanged) onPageChanged();
		}
	}
}

void BCR2000FrontPanel::show(midikraft::PatchParameters const& parameters, bool editable)
{
	parameters_ = editable ? parameters : midikraft::PatchParameters();
	auto previousIds = pageIndex_ >= 0 ? pages_[static_cast<size_t>(pageIndex_)].ids : std::vector<std::string>();
	pages_ = knob_pages::makePages(parameters_);
	pageIndex_ = knob_pages::pageIndexFor(pages_, pageTitle_, pageIndex_);
	if (pageIndex_ >= 0) pageTitle_ = pages_[static_cast<size_t>(pageIndex_)].title;
	auto bcr = bcr_.lock();
	if (!bcr) {
		bcr = findBcr();
		if (bcr) {
			connect(bcr);
			return;
		}
	}
	if (!bcr) return;
	programPage(); // Only uploads when the knobs need other ranges
	auto currentIds = pageIndex_ >= 0 ? pages_[static_cast<size_t>(pageIndex_)].ids : std::vector<std::string>();
	if (currentIds != previousIds && onPageChanged) onPageChanged();
}

void BCR2000FrontPanel::reload()
{
	presetLoaded_ = false;
	programmedPage_.clear();
	knobValues_.clear();
	programPage();
}

midikraft::PatchParameter const* BCR2000FrontPanel::parameterOnKnob(int knob) const
{
	if (pageIndex_ < 0 || knob < 0) return nullptr;
	auto const& ids = pages_[static_cast<size_t>(pageIndex_)].ids;
	if (static_cast<size_t>(knob) >= ids.size() || ids[static_cast<size_t>(knob)].empty()) return nullptr;
	for (auto const& parameter : parameters_) {
		if (parameter.id == ids[static_cast<size_t>(knob)]) return &parameter;
	}
	return nullptr;
}

std::map<std::string, int> BCR2000FrontPanel::knobAssignments() const
{
	std::map<std::string, int> result;
	if (bcr_.expired() || pageIndex_ < 0) return result;
	auto const& ids = pages_[static_cast<size_t>(pageIndex_)].ids;
	for (size_t i = 0; i < ids.size(); ++i) {
		if (!ids[i].empty()) result[ids[i]] = static_cast<int>(i) + 1;
	}
	return result;
}

std::string BCR2000FrontPanel::status() const
{
	if (bcr_.expired() || pageIndex_ < 0) return {};
	return fmt::format("BCR2000: {} ({} of {})", pages_[static_cast<size_t>(pageIndex_)].title, pageIndex_ + 1, pages_.size());
}

void BCR2000FrontPanel::handleMessage(MidiMessage const& message)
{
	if (message.isSysEx()) {
		auto data = message.getSysExData();
		if (!upload_.empty() && midikraft::BCR2000::isSysexFromBCR2000(message) && message.getSysExDataSize() == 9 && data[5] == kBclReply) {
			int line = (data[6] << 7) | data[7];
			if (data[8] != 0) {
				auto index = static_cast<size_t>(line);
				auto text = index < upload_.size() ? midikraft::BCR2000::convertSyxToText(upload_[index]) : std::string();
				spdlog::error("BCR2000 refused line {} of the front panel setup (error {}): {}", line + 1, static_cast<int>(data[8]), text);
			}
			sendNextLine();
		}
		return;
	}
	if (message.getChannel() != knob_pages::kMidiChannel) return;
	int controller = message.getControllerNumber();
	int value = message.getControllerValue();
	if (controller == knob_pages::kPreviousPageController || controller == knob_pages::kNextPageController) {
		if (value > 0) turnPage(controller == knob_pages::kNextPageController ? 1 : -1);
		return;
	}
	int knob = knob_pages::knobForController(controller);
	auto parameter = parameterOnKnob(knob);
	if (!parameter || !upload_.empty()) return; // Ignore knobs while their ranges are being changed
	knobValues_[knob] = value;
	int newValue = knob_pages::fromKnobValue(*parameter, value);
	if (newValue != parameter->value && onKnobTurned) onKnobTurned(parameter->id, newValue);
}

void BCR2000FrontPanel::turnPage(int delta)
{
	if (pages_.empty()) return;
	int count = static_cast<int>(pages_.size());
	pageIndex_ = ((pageIndex_ + delta) % count + count) % count;
	pageTitle_ = pages_[static_cast<size_t>(pageIndex_)].title;
	programPage();
	if (onPageChanged) onPageChanged();
}

void BCR2000FrontPanel::programPage()
{
	auto bcr = bcr_.lock();
	if (!bcr || pageIndex_ < 0) return;
	auto const& page = pages_[static_cast<size_t>(pageIndex_)];
	auto pageBcl = knob_pages::pageBcl(page, parameters_);
	if (!upload_.empty()) {
		if (pageBcl != uploadingPage_) uploadAgain_ = true;
		return;
	}
	if (presetLoaded_ && pageBcl == programmedPage_) {
		sendValues();
		return;
	}
	auto bcl = presetLoaded_ ? pageBcl : knob_pages::presetBcl(page, parameters_);
	upload_ = bcr->convertToSyx(bcl);
	uploadNext_ = 0;
	uploadingPage_ = pageBcl;
	uploadAgain_ = false;
	sendNextLine();
}

void BCR2000FrontPanel::sendNextLine()
{
	auto bcr = bcr_.lock();
	if (!bcr) return;
	if (uploadNext_ >= upload_.size()) {
		finishUpload(true);
		return;
	}
	lastUploadActivity_ = Time::currentTimeMillis();
	midikraft::MidiController::instance()->getMidiOutput(bcr->midiOutput())->sendMessageNow(upload_[uploadNext_++]);
}

void BCR2000FrontPanel::finishUpload(bool ok)
{
	upload_.clear();
	uploadNext_ = 0;
	if (ok) {
		presetLoaded_ = true;
		programmedPage_ = uploadingPage_;
	}
	else {
		presetLoaded_ = false;
		programmedPage_.clear();
		uploadAgain_ = false;
	}
	knobValues_.clear(); // New ranges: send every value again
	if (uploadAgain_) {
		programPage();
	}
	else if (ok) {
		sendValues();
	}
}

void BCR2000FrontPanel::sendValues()
{
	auto bcr = bcr_.lock();
	if (!bcr || pageIndex_ < 0) return;
	auto output = midikraft::MidiController::instance()->getMidiOutput(bcr->midiOutput());
	for (int knob = 0; knob < knob_pages::kKnobsPerPage; ++knob) {
		auto parameter = parameterOnKnob(knob);
		int value = parameter ? knob_pages::toKnobValue(*parameter, parameter->value) : 0;
		auto known = knobValues_.find(knob);
		if (known != knobValues_.end() && known->second == value) continue;
		output->sendMessageNow(MidiMessage::controllerEvent(knob_pages::kMidiChannel, knob_pages::kFirstKnobController + knob, value));
		knobValues_[knob] = value;
	}
}
