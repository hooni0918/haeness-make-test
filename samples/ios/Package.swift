// swift-tools-version: 6.0
import PackageDescription

// HES Swift 게이트가 실제로 검증하는 대상 샘플.
// `swift build` 로 컴파일되며, 모든 소스는 HES 의 *.swift 규칙을 통과한다.
let package = Package(
    name: "CounterFeature",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "CounterFeature", targets: ["CounterFeature"]),
    ],
    targets: [
        .target(name: "CounterFeature"),
    ]
)
