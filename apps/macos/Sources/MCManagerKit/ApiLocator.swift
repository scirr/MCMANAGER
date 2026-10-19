import Foundation

public enum ApiLocator {
    public static let socketName = "api.sock"
    public static let launchAgentLabel = "io.github.scirr.mcmanager"

    public static func runFolders(environment: [String: String] = ProcessInfo.processInfo.environment,
                                  home: String = NSHomeDirectory()) -> [String] {
        var folders: [String] = []
        if let explicit = environment["MCMANAGER_RUN_DIR"], !explicit.isEmpty {
            folders.append(explicit)
        }
        let plist = home + "/Library/LaunchAgents/" + launchAgentLabel + ".plist"
        if let dictionary = NSDictionary(contentsOfFile: plist),
           let base = dictionary["WorkingDirectory"] as? String, !base.isEmpty {
            folders.append(base + "/run")
        }
        folders.append(home + "/Library/Application Support/MCManager/run")
        folders.append(home + "/MCManager/run")
        folders.append(home + "/MCMANAGER/macOS/run")
        return folders
    }

    public static func socketPath(runFolders: [String]? = nil,
                                  fileExists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }) -> String? {
        for folder in runFolders ?? Self.runFolders() {
            let path = folder + "/" + socketName
            if fileExists(path) { return path }
        }
        return nil
    }
}
