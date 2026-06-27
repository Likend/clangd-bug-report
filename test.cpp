template <typename T>
concept test_concept = requires { T::type; };
//      ↑ request [textDocument/typeDefinition]
