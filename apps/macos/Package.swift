// swift-tools-version:5.10
import PackageDescription

let package = Package(
    name: "MCManager",
    defaultLocalization: "en",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "MCManagerKit", targets: ["MCManagerKit"]),
        .executable(name: "MCManagerApp", targets: ["MCManagerApp"]),
    ],
    targets: [
        .target(name: "MCManagerKit"),
        .executableTarget(
            name: "MCManagerApp",
            dependencies: ["MCManagerKit"],
            resources: [.process("Localizable.xcstrings")]
        ),
        .testTarget(name: "MCManagerKitTests", dependencies: ["MCManagerKit"]),
    ]
)
