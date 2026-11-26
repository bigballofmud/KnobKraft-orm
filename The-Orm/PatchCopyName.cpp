#include "PatchCopyName.h"

#include <algorithm>
#include <cctype>

namespace {

	std::string trimRight(std::string const& s) {
		auto end = s.find_last_not_of(' ');
		return end == std::string::npos ? std::string() : s.substr(0, end + 1);
	}

	bool endsWith(std::string const& s, std::string const& suffix) {
		return s.size() >= suffix.size() && s.compare(s.size() - suffix.size(), suffix.size(), suffix) == 0;
	}

	// The stored name for base + suffix, shortening base until the synth keeps the whole suffix; empty if it never does
	std::string fitted(std::string const& base, std::string const& suffix, std::function<std::string(std::string const&)> const& store) {
		for (size_t keep = base.size(); keep > 0; --keep) {
			auto shortened = trimRight(base.substr(0, keep));
			if (shortened.empty()) break;
			auto stored = trimRight(store(shortened + suffix));
			if (stored.size() > suffix.size() && endsWith(stored, suffix)) return stored;
		}
		return {};
	}

}

namespace patch_copy_name {

	std::string nameForCopy(std::string const& original,
		std::function<bool(std::string const&)> const& taken,
		std::function<std::string(std::string const&)> const& store)
	{
		std::string base = trimRight(original);
		int number = 2;
		auto space = base.find_last_of(' ');
		if (space != std::string::npos && space > 0 && base.size() - space - 1 <= 3) {
			auto digits = base.substr(space + 1);
			auto prefix = trimRight(base.substr(0, space));
			bool allDigits = !digits.empty() && std::all_of(digits.begin(), digits.end(), [](unsigned char c) { return std::isdigit(c) != 0; });
			if (allDigits && !prefix.empty() && taken(prefix)) {
				base = prefix;
				number = std::max(2, std::stoi(digits) + 1);
			}
		}
		if (base.empty()) return original;
		for (; number < 1000; ++number) {
			auto name = fitted(base, " " + std::to_string(number), store);
			if (name.empty()) return original;
			if (!taken(name)) return name;
		}
		return original;
	}

}
