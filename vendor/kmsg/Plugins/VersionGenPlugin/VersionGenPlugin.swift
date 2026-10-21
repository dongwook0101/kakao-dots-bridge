import PackagePlugin

@main
struct VersionGenPlugin: BuildToolPlugin {
    func createBuildCommands(context: PluginContext, target: Target) throws -> [Command] {
        guard target is SourceModuleTarget else {
            return []
        }

        let versionFile = context.package.directoryURL.appendingPathComponent("VERSION")
        let outputFile = context.pluginWorkDirectoryURL.appendingPathComponent("GeneratedVersion.swift")
        let tool = try context.tool(named: "VersionGenTool")

        return [
            .buildCommand(
                displayName: "Generating build version from VERSION",
                executable: tool.url,
                arguments: [
                    versionFile.path,
                    outputFile.path,
                ],
                inputFiles: [versionFile],
                outputFiles: [outputFile]
            )
        ]
    }
}
