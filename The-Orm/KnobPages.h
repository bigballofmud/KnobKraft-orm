#pragma once

#include "PatchParametersCapability.h"

#include <string>
#include <vector>

// Lays the parameter grid out on a BCR2000's knobs, one page at a time.
// A page holds up to 32 parameters of one grid section: knobs 1-8 are the top row of push encoders
// (encoder group 1), knobs 9-32 the three rows of encoders below. A first section of at most 8 parameters
// (the GR-50's Common) stays on the top row of every page, and the pages then use only the rows below.
// The BCR2000 sends each knob as a CC on its own channel; the app keeps the page and maps the CC to a parameter.
namespace knob_pages {

	constexpr int kKnobsPerPage = 32;
	constexpr size_t kTopRowKnobs = 8;
	constexpr int kMidiChannel = 16; // One-based, as BCL writes it
	constexpr int kFirstKnobController = 1; // Knob k sends CC 1+k
	constexpr int kPreviousPageController = 102; // The first two of the four user buttons at the lower right
	constexpr int kNextPageController = 103;
	constexpr int kPreviousPageButton = 49;
	constexpr int kNextPageButton = 50;

	struct Page {
		std::string title; // The grid section, numbered when it takes several pages, e.g. "Partial 1 (2/2)"
		std::vector<std::string> ids; // Parameter id on each knob, knob 0 first; empty where a knob has none
	};

	// Editable parameters with a range, grouped by section in grid order, with a small first section pinned to the top row
	std::vector<Page> makePages(midikraft::PatchParameters const& parameters);

	// The page with this title, else the one at fallback (clamped), so turning to another patch keeps the place
	int pageIndexFor(std::vector<Page> const& pages, std::string const& title, int fallback);

	// The BCL encoder number of a knob (0-31)
	int encoderNumber(int knob);

	// The CC values a knob sends for a parameter. Ranges inside 0-127 are sent as they are, one value per
	// step; others are spread over 0-127 and scaled.
	struct KnobRange {
		int low = 0;
		int high = 127;
		bool scaled = false;
	};
	KnobRange knobRange(midikraft::PatchParameter const& parameter);
	int toKnobValue(midikraft::PatchParameter const& parameter, int value);
	int fromKnobValue(midikraft::PatchParameter const& parameter, int knobValue);

	// Which knob (0-31) a CC number belongs to, or -1
	int knobForController(int controller);

	// The whole preset, sent once: page buttons plus the knobs set up for the given page
	std::string presetBcl(Page const& page, midikraft::PatchParameters const& parameters);
	// Only the knob ranges, sent when the page changes. Knobs without a parameter are switched off.
	std::string pageBcl(Page const& page, midikraft::PatchParameters const& parameters);

}
