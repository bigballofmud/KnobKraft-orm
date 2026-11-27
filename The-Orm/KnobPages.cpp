#include "KnobPages.h"

#include <fmt/format.h>

#include <algorithm>
#include <map>

namespace knob_pages {

	namespace {
		bool hasRange(midikraft::PatchParameter const& parameter) {
			return parameter.editable && parameter.minValue && parameter.maxValue && *parameter.minValue < *parameter.maxValue;
		}

		midikraft::PatchParameter const* find(midikraft::PatchParameters const& parameters, std::string const& id) {
			for (auto const& parameter : parameters) {
				if (parameter.id == id) return &parameter;
			}
			return nullptr;
		}

		std::string encoderBcl(int knob, midikraft::PatchParameter const* parameter) {
			int controller = kFirstKnobController + knob;
			if (!parameter) {
				// Nothing on this knob: a zero range, so turning it sends nothing new, and no LEDs
				return fmt::format("$encoder {}\n  .easypar CC {} {} 0 0 absolute\n  .mode off\n  .showvalue off\n",
					encoderNumber(knob), kMidiChannel, controller);
			}
			auto range = knobRange(*parameter);
			return fmt::format("$encoder {}\n  .easypar CC {} {} {} {} absolute\n  .mode 1dot\n  .showvalue on\n  .resolution 64 64 127 127\n",
				encoderNumber(knob), kMidiChannel, controller, range.low, range.high);
		}

		std::string encodersBcl(Page const& page, midikraft::PatchParameters const& parameters) {
			std::string result;
			for (int knob = 0; knob < kKnobsPerPage; ++knob) {
				auto index = static_cast<size_t>(knob);
				result += encoderBcl(knob, index < page.ids.size() ? find(parameters, page.ids[index]) : nullptr);
			}
			return result;
		}

		std::string buttonBcl(int button, int controller) {
			// Sends 127 when pressed and 0 when let go; the LED lights while it is held
			return fmt::format("$button {}\n  .easypar CC {} {} 127 0 toggleoff\n  .mode down\n  .showvalue off\n", button, kMidiChannel, controller);
		}
	}

	std::vector<Page> makePages(midikraft::PatchParameters const& parameters) {
		// Sections in the order the grid shows them
		std::vector<std::string> order;
		std::map<std::string, std::vector<std::string>> idsByGroup;
		for (auto const& parameter : parameters) {
			if (!hasRange(parameter)) continue;
			if (idsByGroup.find(parameter.group) == idsByGroup.end()) order.push_back(parameter.group);
			idsByGroup[parameter.group].push_back(parameter.id);
		}

		std::vector<Page> result;
		for (auto const& group : order) {
			auto const& ids = idsByGroup[group];
			auto count = (ids.size() + kKnobsPerPage - 1) / kKnobsPerPage;
			std::string title = group.empty() ? "Parameters" : group;
			for (size_t i = 0; i < count; ++i) {
				Page page;
				page.title = count > 1 ? fmt::format("{} ({}/{})", title, i + 1, count) : title;
				auto begin = ids.begin() + static_cast<std::ptrdiff_t>(i * kKnobsPerPage);
				auto end = ids.begin() + static_cast<std::ptrdiff_t>(std::min(ids.size(), (i + 1) * kKnobsPerPage));
				page.ids.assign(begin, end);
				result.push_back(page);
			}
		}
		return result;
	}

	int pageIndexFor(std::vector<Page> const& pages, std::string const& title, int fallback) {
		if (pages.empty()) return -1;
		for (size_t i = 0; i < pages.size(); ++i) {
			if (pages[i].title == title) return static_cast<int>(i);
		}
		return std::clamp(fallback, 0, static_cast<int>(pages.size()) - 1);
	}

	int encoderNumber(int knob) {
		return knob < 8 ? knob + 1 : 33 + (knob - 8);
	}

	KnobRange knobRange(midikraft::PatchParameter const& parameter) {
		if (!hasRange(parameter)) return { 0, 0, false };
		if (*parameter.minValue >= 0 && *parameter.maxValue <= 127) return { *parameter.minValue, *parameter.maxValue, false };
		return { 0, 127, true };
	}

	int toKnobValue(midikraft::PatchParameter const& parameter, int value) {
		auto range = knobRange(parameter);
		if (!hasRange(parameter)) return 0;
		value = std::clamp(value, *parameter.minValue, *parameter.maxValue);
		if (!range.scaled) return value;
		auto span = static_cast<long long>(*parameter.maxValue) - *parameter.minValue;
		return static_cast<int>(((value - *parameter.minValue) * 127LL + span / 2) / span);
	}

	int fromKnobValue(midikraft::PatchParameter const& parameter, int knobValue) {
		auto range = knobRange(parameter);
		if (!hasRange(parameter)) return parameter.value;
		knobValue = std::clamp(knobValue, range.low, range.high);
		if (!range.scaled) return knobValue;
		auto span = static_cast<long long>(*parameter.maxValue) - *parameter.minValue;
		return *parameter.minValue + static_cast<int>((knobValue * span + 63) / 127);
	}

	int knobForController(int controller) {
		int knob = controller - kFirstKnobController;
		return knob >= 0 && knob < kKnobsPerPage ? knob : -1;
	}

	std::string presetBcl(Page const& page, midikraft::PatchParameters const& parameters) {
		return "$rev R1\n"
			"$preset\n"
			"  .name 'KnobKraft grid'\n"
			"  .snapshot off\n"
			"  .request off\n"
			"  .egroups 4\n"
			"  .fkeys off\n" // Else the four lower right buttons change presets instead of sending
			"  .lock off\n"
			"  .init\n"
			+ buttonBcl(kPreviousPageButton, kPreviousPageController)
			+ buttonBcl(kNextPageButton, kNextPageController)
			+ encodersBcl(page, parameters)
			+ "$end\n";
	}

	std::string pageBcl(Page const& page, midikraft::PatchParameters const& parameters) {
		return "$rev R1\n" + encodersBcl(page, parameters) + "$end\n";
	}

}
