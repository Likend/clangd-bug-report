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

// struct RGB { static constexpr uint8_t channels = 3; using value_type = uint8_t; };

template <color_space CS>
class ImageSpan {
   public:
    static constexpr size_t channels = static_cast<size_t>(CS::channels);
    using value_type                 = typename CS::value_type;
    using pixel_type                 = std::span<value_type, channels>;

    class ImageFlat {
       public:
        class Iterator {
           public:
            using difference_type   = std::ptrdiff_t;
            int offsetInRow = 0;
            int rowWidth = 0;

            Iterator& operator+=(difference_type n) {
                int r = offsetInRow + n;
                if (r >= rowWidth) {
                    // 带有 /*TARGET*/ 的致命错字
                    r = offsetInRow + r - ro/*TARGET*/
                }
                return *this;
            }
        };
    };
};
}
