#include "PatchEditSession.h"

#include "Capability.h"
#include "MidiLocationCapability.h"
#include "UploadHandshakeCapability.h"
#include "UploadSequence.h"
#include "PatchParameterViews.h"

#include <spdlog/spdlog.h>

#include <algorithm>

namespace patch_edit_timing {
	namespace {
		constexpr long long kMicrosecondsPerMidiByte = 320; // 10 bits at 31250 baud
		constexpr int kDigestMs = 50;
	}

	int sendIntervalMs(std::vector<juce::MidiMessage> const& messages, int delayPerMessageMs)
	{
		long long microseconds = 0;
		for (auto const& message : messages) {
			microseconds += 1000LL * std::max(0, delayPerMessageMs) + kMicrosecondsPerMidiByte * message.getRawDataSize();
		}
		auto needed = static_cast<int>((microseconds + 999) / 1000) + kDigestMs;
		return std::max(kMinSendIntervalMs, needed);
	}
}

PatchEditSession::~PatchEditSession()
{
	stopTimer();
}

void PatchEditSession::start(std::shared_ptr<midikraft::PatchHolder> original)
{
	stopTimer();
	sendPending_ = false;
	original_ = original;
	current_ = original ? original->patch() : nullptr;
	originalValues_.clear();
	if (canEdit()) {
		for (auto const& parameter : parameters()) {
			originalValues_[parameter.id] = parameter.value;
		}
	}
}

bool PatchEditSession::isEditing(std::shared_ptr<midikraft::DataFile> const& libraryPatch) const
{
	return original_ && libraryPatch && original_->patch() == libraryPatch;
}

midikraft::PatchParametersCapability* PatchEditSession::capability() const
{
	if (!original_ || !original_->synth()) return nullptr;
	return midikraft::Capability::hasCapability<midikraft::PatchParametersCapability>(original_->synth());
}

bool PatchEditSession::usesAdaptation() const
{
	auto cap = capability();
	return cap && current_ && cap->canSetPatchParameters();
}

bool PatchEditSession::canEdit() const
{
	if (!original_ || !current_) return false;
	return usesAdaptation() || patch_parameters::canEditNatively(original_->smartSynth(), current_);
}

bool PatchEditSession::isDirty() const
{
	return original_ && current_ && original_->patch() && current_->data() != original_->patch()->data();
}

bool PatchEditSession::wouldDiscardEdits(std::shared_ptr<midikraft::DataFile> const& next) const
{
	if (!isDirty()) return false;
	return !next || next->data() != current_->data();
}

midikraft::PatchParameters PatchEditSession::parameters() const
{
	if (!original_ || !current_) return {};
	return patch_parameters::parametersFor(original_->smartSynth(), current_);
}

std::set<std::string> PatchEditSession::changedIds() const
{
	std::set<std::string> result;
	if (!isDirty()) return result;
	for (auto const& parameter : parameters()) {
		auto original = originalValues_.find(parameter.id);
		if (original == originalValues_.end() || original->second != parameter.value) {
			result.insert(parameter.id);
		}
	}
	return result;
}

bool PatchEditSession::setValue(std::string const& id, int value)
{
	if (!canEdit()) return false;
	std::shared_ptr<midikraft::DataFile> edited;
	if (usesAdaptation()) {
		edited = capability()->setPatchParameters(*current_, { { id, value } });
	}
	else {
		edited = patch_parameters::applyNativeValue(original_->smartSynth(), current_, original_->patchNumber(), id, value);
	}
	if (!edited) {
		spdlog::warn("Could not set parameter {} to {} for {}", id, value, original_->name());
		return false;
	}
	current_ = edited;
	scheduleSend();
	return true;
}

void PatchEditSession::revert()
{
	if (!isDirty()) return;
	current_ = original_->patch();
	scheduleSend();
}

std::shared_ptr<midikraft::PatchHolder> PatchEditSession::makeEditedPatch() const
{
	if (!isDirty()) return nullptr;
	// Give the copy its own data, as renaming it may write into the bytes (synths that store the name in the patch).
	// The database rebuilds patches the same way when loading them.
	auto synth = original_->smartSynth();
	auto copy = synth ? synth->patchFromPatchData(current_->data(), original_->patchNumber()) : nullptr;
	if (!copy || copy->data() != current_->data()) {
		spdlog::warn("Could not copy the edited patch {}", original_->name());
		return nullptr;
	}
	auto edited = std::make_shared<midikraft::PatchHolder>(synth, original_->sourceInfo(), copy);
	// The data already carries the name on synths that store it; setting it again could re-encode the bytes
	if (edited->name() != original_->name()) edited->setName(original_->name());
	edited->setPatchNumber(original_->patchNumber());
	edited->setBank(original_->bankNumber());
	edited->setFavorite(original_->howFavorite());
	edited->setCategories(original_->categories());
	edited->setUserDecisions(original_->userDecisionSet());
	edited->setComment(original_->comment());
	edited->setAuthor(original_->author());
	edited->setInfo(original_->info());
	return edited;
}

void PatchEditSession::scheduleSend()
{
	sendPending_ = true;
	if (!isTimerRunning()) {
		// Send the first change at once, then no faster than the synth can take it, ending with the latest state
		startTimer(sendNow());
	}
}

void PatchEditSession::timerCallback()
{
	if (sendPending_) {
		auto interval = sendNow();
		if (interval != getTimerInterval()) startTimer(interval);
	}
	else {
		stopTimer();
	}
}

int PatchEditSession::sendNow()
{
	sendPending_ = false;
	if (!original_ || !current_) return patch_edit_timing::kMinSendIntervalMs;
	auto synth = original_->smartSynth();
	auto location = midikraft::Capability::hasCapability<midikraft::MidiLocationCapability>(synth);
	if (!location || !location->channel().isValid()) {
		spdlog::debug("{} not detected, edit not sent", synth ? synth->getName() : "Synth");
		return patch_edit_timing::kMinSendIntervalMs;
	}
	auto messages = synth->dataFileToSysex(current_, nullptr);
	if (messages.empty()) {
		spdlog::warn("{} produced no MIDI messages for the edited patch", synth->getName());
		return patch_edit_timing::kMinSendIntervalMs;
	}
	auto interval = patch_edit_timing::sendIntervalMs(messages, synth->generalMessageDelayMs());
	if (!midikraft::Capability::hasCapability<midikraft::UploadHandshakeCapability>(synth)) {
		// The synth's own send, as some (Kawai K3) treat parts of the dump specially
		synth->sendDataFileToSynth(current_, nullptr);
		return interval;
	}
	// A synth with an upload handshake refuses a send while the previous one is still running; try again next tick
	// rather than losing the latest edit. The flag outlives this session in case the result arrives late.
	auto busy = std::make_shared<bool>(false);
	synth->sendMessagesToSynthWithUploadHandshake(std::move(messages), [busy, synthName = synth->getName()](midikraft::UploadResult const& result) {
		if (result.status == midikraft::UploadResult::Status::BUSY) {
			*busy = true;
		}
		else if (!result.successful()) {
			spdlog::error("Sending the edited patch to {} failed: {}", synthName, result.message);
		}
	});
	if (*busy) sendPending_ = true;
	return interval;
}
