#include "PatchEditSession.h"

#include "Capability.h"
#include "MidiLocationCapability.h"
#include "PatchParameterViews.h"

#include <spdlog/spdlog.h>

namespace {
	// Minimum time between two sends of the edited patch, so a fast drag doesn't flood older synths
	constexpr int kSendIntervalMs = 150;
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
	auto edited = std::make_shared<midikraft::PatchHolder>(original_->smartSynth(), original_->sourceInfo(), current_);
	edited->setName(original_->name());
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
		// Send the first change at once, then at most every kSendIntervalMs, ending with the latest state
		sendNow();
		startTimer(kSendIntervalMs);
	}
}

void PatchEditSession::timerCallback()
{
	if (sendPending_) {
		sendNow();
	}
	else {
		stopTimer();
	}
}

void PatchEditSession::sendNow()
{
	sendPending_ = false;
	if (!original_ || !current_) return;
	auto synth = original_->smartSynth();
	auto location = midikraft::Capability::hasCapability<midikraft::MidiLocationCapability>(synth);
	if (!location || !location->channel().isValid()) {
		spdlog::debug("{} not detected, edit not sent", synth ? synth->getName() : "Synth");
		return;
	}
	synth->sendDataFileToSynth(current_, nullptr);
}
