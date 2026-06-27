#include <cassert>
#include <concepts>
#include <cstddef>
#include <cstdint>
// #include <ranges>
#include <span>

namespace croplines {
template <typename CS>
concept color_space = requires {
    typename CS::value_type;
    requires std::integral<decltype(CS::channels)>;
};


template <color_space CS>
class ImageSpan {
    ImageSpan& function(size_t n) {
        int r =  - ro/*TARGET*/
        return *this;
    }
};
}
