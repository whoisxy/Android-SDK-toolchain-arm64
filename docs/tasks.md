# Dependency tasks

Every row has a `tasks/NAME.sh [HASH_OR_TAG] --libc bionic|glibc|musl` entry point and an individual Actions workflow. Output is always ARM64; libc defaults to bionic.

| Task | Output kind | Backend | Default source commit | Supported libc | Runner |
|---|---|---|---|---|---|
| `aapt` | native-tool | android-sdk-tool | `723419df1a0769b63587722a8a0a0980f454ffd2` | bionic | ubuntu-24.04 |
| `aapt2` | native-tool | android-sdk-tool | `723419df1a0769b63587722a8a0a0980f454ffd2` | bionic | ubuntu-24.04 |
| `abseil` | native-library | cmake | `564023aa53767b5f60b3a556f0a025b7b7e8241e` | bionic, glibc, musl | ubuntu-24.04 |
| `adb` | native-tool | android-sdk-tool | `ce9ea51f30f69f7560db692f7cb4d5d5502c3653` | bionic | ubuntu-24.04 |
| `aidl` | native-tool | android-sdk-tool | `4e2b7b3dc8c8ac9ae3fabec9460dd6d99f92a6ab` | bionic | ubuntu-24.04 |
| `apksigner` | jvm-tool | apksigner | `5bd2e81b765cd0da6f0b6378d78b19abff04fe26` | bionic, glibc, musl | ubuntu-24.04 |
| `benchmark` | native-library | cmake | `431abd149fd76a072f821913c0340137cc755f36` | bionic, glibc, musl | ubuntu-24.04 |
| `boringssl` | native-library | cmake | `c7eb007fd10627f1abb41a3e368b85e24cd20af9` | bionic, glibc, musl | ubuntu-24.04 |
| `brotli` | native-library | cmake | `350100a5bb9d9671aca85213b2ec7a70a361b0cd` | bionic, glibc, musl | ubuntu-24.04 |
| `cipd` | native-tool | go | `0cfda84e9220a0a161aa4f6b37e3eea5325d81d2` | bionic, glibc, musl | ubuntu-24.04 |
| `cpu-features` | native-library | cmake | `936b9ab5515dead115606559502e3864958f7f6e` | bionic, glibc, musl | ubuntu-24.04 |
| `dart-sdk` | sdk | dart-sdk | `416e33b0ffaef062a60ec966bb8c82ed2b83f128` | bionic, glibc | ubuntu-24.04 |
| `depot-tools` | script-and-native-distribution | depot-tools | `580b4ff3f5cd0dcaa2eacda28cefe0f45320e8f7` | bionic, glibc, musl | ubuntu-24.04 |
| `expat` | native-library | cmake | `8e49998f003d693213b538ef765814c7d21abada` | bionic, glibc, musl | ubuntu-24.04 |
| `fastboot` | native-tool | android-sdk-tool | `90e4908e776d2be9b26b87af649e63e4208cf085` | bionic | ubuntu-24.04 |
| `flatbuffers` | native-library-and-tools | cmake | `067bfdbde9b10c1beb5d6b02d67ae9db8b96f736` | bionic, glibc, musl | ubuntu-24.04 |
| `flutter-engine-arm64` | android-engine | android-engine | `c197ca5199e9ee5661e865596c9c07294dfab51c` | bionic | ubuntu-24.04 |
| `flutter-tools` | tool-kernel-with-arm64-sdk | flutter-tools | `c197ca5199e9ee5661e865596c9c07294dfab51c` | bionic, glibc | ubuntu-24.04 |
| `freetype` | native-library | cmake | `be4bcb57914154fc1b9e2900bf8e4b516057e2b8` | bionic, glibc, musl | ubuntu-24.04 |
| `gen-snapshot` | native-tool | gen-snapshot | `416e33b0ffaef062a60ec966bb8c82ed2b83f128` | bionic, glibc | ubuntu-24.04 |
| `glfw` | native-library | cmake | `9352d8fe93cd443be18157abe81f16500549aec0` | glibc, musl | ubuntu-24.04 |
| `glslang` | native-library-and-tools | cmake | `a57276bf558f5cf94d3a9854ebdf5a2236849a5a` | bionic, glibc, musl | ubuntu-24.04 |
| `gn` | native-tool | gn | `81b24e01531ecf0eff12ec9359a555ec3944ec4e` | bionic, glibc, musl | ubuntu-24.04 |
| `googletest` | native-library | cmake | `e9907112b47255d50b4d343e7e2160bce8dc85d1` | bionic, glibc, musl | ubuntu-24.04 |
| `gtest-parallel` | script-distribution | gtest-parallel | `38191e2733d7cbaeaef6a3f1a942ddeb38a2ad14` | bionic, glibc, musl | ubuntu-24.04 |
| `harfbuzz` | native-library | cmake | `49844c32a7a3f6be371355a1213c952a3f4a44e7` | bionic, glibc, musl | ubuntu-24.04 |
| `icu` | native-library | icu | `d578f2e8b7bd5938e21cfb6bf15c079e0aa5b738` | bionic, glibc, musl | ubuntu-24.04 |
| `inja` | headers | cmake | `88bd6112575a80d004e551c98cf956f88ff4d445` | bionic, glibc, musl | ubuntu-24.04 |
| `libjpeg-turbo` | native-library | cmake | `0fb821f3b2e570b2783a94ccd9a2fb1f4916ae9f` | bionic, glibc, musl | ubuntu-24.04 |
| `libpng` | native-library | cmake | `ced6b6c0c1e24716423a417b399d3c7d4623890d` | bionic, glibc, musl | ubuntu-24.04 |
| `libtess2` | native-library | libtess2 | `725e5e08ec8751477565f1d603fd7eb9058c277c` | bionic, glibc, musl | ubuntu-24.04 |
| `libwebp` | native-library | cmake | `ca332209cb5567c9b249c86788cb2dbf8847e760` | bionic, glibc, musl | ubuntu-24.04 |
| `ninja` | native-tool | cmake | `a524bf3f6bacd1b4ad85d719eed2737d8562f27a` | bionic, glibc, musl | ubuntu-24.04 |
| `nlohmann-json` | headers | cmake | `17d9eacd248f58b73f4d1be518ef649fe2295642` | bionic, glibc, musl | ubuntu-24.04 |
| `rapidjson` | headers | cmake | `47253cab97e9cfe99dbd6b90836fc11589d7d802` | bionic, glibc, musl | ubuntu-24.04 |
| `re2` | native-library | cmake | `c84a140c93352cdabbfb547c531be34515b12228` | bionic, glibc, musl | ubuntu-24.04 |
| `shaderc` | native-library-and-tools | shaderc | `d15277d6bc180f6a0b8b601f0cab2bbcaac9b4d5` | bionic, glibc, musl | ubuntu-24.04 |
| `skia` | native-library | skia | `8df24be66531469e576a806749a0202ae26b8d08` | bionic, glibc | self-hosted, linux, x64, sdk-builder |
| `spirv-cross` | native-library-and-tools | cmake | `b8fcf307f1f347089e3c46eb4451d27f32ebc8d3` | bionic, glibc, musl | ubuntu-24.04 |
| `spirv-headers` | headers | cmake | `01e0577914a75a2569c846778c2f93aa8e6feddd` | bionic, glibc, musl | ubuntu-24.04 |
| `spirv-tools` | native-library-and-tools | cmake | `19042c8921f35f7bec56b9e5c96c5f5691588ca8` | bionic, glibc, musl | ubuntu-24.04 |
| `sqlite` | native-library | sqlite | `0f61bd2023ba94423b4e4c8cfb1a23de1fe6a21c` | bionic, glibc, musl | ubuntu-24.04 |
| `vulkan-headers` | headers | cmake | `a4f8ada9f4f97c45b8c89c57997be9cebaae65d2` | bionic, glibc, musl | ubuntu-24.04 |
| `vulkan-memory-allocator` | headers | cmake | `c788c52156f3ef7bc7ab769cb03c110a53ac8fcb` | bionic, glibc, musl | ubuntu-24.04 |
| `zipalign` | native-tool | android-sdk-tool | `46581c7be3390d0ecd0a037e6e6ebc2893d5768a` | bionic | ubuntu-24.04 |
| `zlib` | native-library | cmake | `51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf` | bionic, glibc, musl | ubuntu-24.04 |

These are implemented recipes, not a claim that every recipe has completed a CI build. Consult Actions and Releases for observed results.
Refs must belong to the recipe's source repository. Different upstream versions may need recipe changes. Bootstrap-only sources such as repo are excluded from release tasks.
