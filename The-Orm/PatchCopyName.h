#pragma once

#include <functional>
#include <string>

namespace patch_copy_name {

	// Name for a saved copy of a patch: the original's name with a number, "Pedal Steel" -> "Pedal Steel 2".
	// - taken(name) says whether a patch of the same synth already has that name; the lowest free number is used.
	// - A name that is itself a numbered copy ("Pedal Steel 2", where "Pedal Steel" exists) counts on: "Pedal Steel 3".
	// - store(name) returns the name as the synth would keep it, e.g. cut to its length. When the number would be
	//   cut off, the base name is shortened instead, so the number always shows.
	// Returns the original name if no numbered name fits.
	std::string nameForCopy(std::string const& original,
		std::function<bool(std::string const&)> const& taken,
		std::function<std::string(std::string const&)> const& store);

}
