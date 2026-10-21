import ArgumentParser
import Foundation

struct InspectCommand: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "inspect",
        abstract: "Inspect KakaoTalk UI hierarchy for debugging"
    )

    @Option(name: .shortAndLong, help: "Maximum depth to traverse")
    var depth: Int = 4

    @Option(name: .shortAndLong, help: "Window index to inspect (default: main window)")
    var window: Int?

    @Flag(name: .long, help: "Show all attributes for each element")
    var showAttributes: Bool = false

    @Flag(name: .long, help: "Show AX hierarchy path for each element")
    var showPath: Bool = false

    @Flag(name: .long, help: "Show frame for each element")
    var showFrame: Bool = false

    @Flag(name: .long, help: "Show sibling index for each element")
    var showIndex: Bool = false

    @Flag(name: .long, help: "Show state flags (enabled/focused/selected/editable)")
    var showFlags: Bool = false

    @Flag(name: .long, help: "Show supported AX actions")
    var showActions: Bool = false

    @Flag(name: .long, help: "Enable debug layout bundle (path/frame/index/flags)")
    var debugLayout: Bool = false

    @Flag(name: .long, help: "Print per-row summary for message parsing diagnostics")
    var rowSummary: Bool = false

    @Option(name: .long, help: "Row summary range start:end (inclusive, zero-based)")
    var rowRange: String?

    func run() throws {
        guard AccessibilityPermission.ensureGranted(autoPrompt: false, openSettingsOnFailure: false) else {
            AccessibilityPermission.printInstructions()
            throw ExitCode.failure
        }

        let kakao = try KakaoTalkApp()

        // Activate and wait for window if not visible
        var windows = kakao.windows
        if windows.isEmpty {
            print("No windows found, activating KakaoTalk...")
            _ = kakao.activateAndWaitForWindow(timeout: 3.0)
            windows = kakao.windows
        }

        guard !windows.isEmpty else {
            print("No KakaoTalk windows found.")
            throw ExitCode.failure
        }

        let targetWindow: UIElement
        if let windowIndex = window {
            guard windowIndex >= 0 && windowIndex < windows.count else {
                print("Invalid window index. Available windows: 0-\(windows.count - 1)")
                throw ExitCode.failure
            }
            targetWindow = windows[windowIndex]
        } else {
            targetWindow = kakao.mainWindow ?? windows[0]
        }

        let windowTitle = targetWindow.title ?? "(untitled)"
        print("Inspecting window: \(windowTitle)\n")

        let rootPath = "\(targetWindow.role ?? "AXUnknown")[0]"
        printElement(
            targetWindow,
            depth: 0,
            maxDepth: depth,
            path: rootPath,
            siblingIndex: nil,
            siblingCount: nil
        )

        let parsedRowRange = try parseRowRange()
        if rowSummary {
            print("")
            printRowSummary(from: targetWindow, range: parsedRowRange)
        } else if parsedRowRange != nil {
            print("\nNote: --row-range applies only with --row-summary.")
        }
    }

    private var effectiveShowPath: Bool { showPath || debugLayout }
    private var effectiveShowFrame: Bool { showFrame || debugLayout }
    private var effectiveShowIndex: Bool { showIndex || debugLayout }
    private var effectiveShowFlags: Bool { showFlags || debugLayout }

    private func printElement(
        _ element: UIElement,
        depth: Int,
        maxDepth: Int,
        path: String,
        siblingIndex: Int?,
        siblingCount: Int?
    ) {
        guard depth <= maxDepth else {
            let childCount = element.children.count
            if childCount > 0 {
                let indent = String(repeating: "  ", count: depth)
                print("\(indent)... (\(childCount) more children)")
            }
            return
        }

        let indent = String(repeating: "  ", count: depth)
        var info: [String] = []

        if let role = element.role {
            info.append("role: \(role)")
        }
        if let title = element.title, !title.isEmpty {
            info.append("title: \"\(title.prefix(40))\(title.count > 40 ? "..." : "")\"")
        }
        if let identifier = element.identifier, !identifier.isEmpty {
            info.append("id: \(identifier)")
        }
        if let value = element.stringValue, !value.isEmpty {
            let truncated = value.prefix(30)
            info.append("value: \"\(truncated)\(value.count > 30 ? "..." : "")\"")
        }
        if element.isFocused {
            info.append("focused")
        }
        if effectiveShowFrame {
            info.append("frame: \(frameDescription(element.frame))")
        }
        if effectiveShowIndex, let siblingIndex, let siblingCount {
            info.append("sibling: \(siblingIndex + 1)/\(siblingCount)")
        }
        if effectiveShowFlags {
            let flags = elementStateFlags(element)
            if !flags.isEmpty {
                info.append("flags: \(flags.joined(separator: "|"))")
            }
        }
        if showActions {
            let actions = (try? element.actionNames()) ?? []
            if !actions.isEmpty {
                let preview = actions.prefix(8).joined(separator: "|")
                let suffix = actions.count > 8 ? "|..." : ""
                info.append("actions: \(preview)\(suffix)")
            }
        }
        if effectiveShowPath {
            info.append("path: \(path)")
        }

        print("\(indent)[\(info.joined(separator: ", "))]")

        if showAttributes {
            do {
                let attrs = try element.attributeNames()
                let attrIndent = indent + "  "
                for attr in attrs.prefix(20) {
                    if let val: Any = element.attributeOptional(attr) {
                        print("\(attrIndent)\(attr) = \(String(describing: val).prefix(50))")
                    }
                }
            } catch {
                // Ignore attribute errors
            }
        }

        let children = element.children
        for (index, child) in children.enumerated() {
            let childRole = child.role ?? "AXUnknown"
            let childPath = "\(path)/\(childRole)[\(index)]"
            printElement(
                child,
                depth: depth + 1,
                maxDepth: maxDepth,
                path: childPath,
                siblingIndex: index,
                siblingCount: children.count
            )
        }
    }

    private func elementStateFlags(_ element: UIElement) -> [String] {
        var flags: [String] = []
        flags.append(element.isEnabled ? "enabled" : "disabled")
        if element.isFocused {
            flags.append("focused")
        }
        let isSelected: Bool = element.attributeOptional("AXSelected") ?? false
        if isSelected {
            flags.append("selected")
        }
        let isEditable: Bool = element.attributeOptional(kAXEditableAttribute) ?? false
        if isEditable {
            flags.append("editable")
        }
        return flags
    }

    private func parseRowRange() throws -> ClosedRange<Int>? {
        guard let rowRange else { return nil }

        let trimmed = rowRange.trimmingCharacters(in: .whitespacesAndNewlines)
        let parts = trimmed.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2, let start = Int(parts[0]), let end = Int(parts[1]), start >= 0, end >= start else {
            print("Invalid --row-range '\(rowRange)'. Use start:end (inclusive, zero-based).")
            throw ExitCode.failure
        }
        return start...end
    }

    private func printRowSummary(from root: UIElement, range: ClosedRange<Int>?) {
        let rows = root.findAll(role: kAXRowRole, limit: 2_000, maxNodes: 20_000)
        let sortedRows = rows.sorted { lhs, rhs in
            let lhsY = lhs.frame?.minY ?? .greatestFiniteMagnitude
            let rhsY = rhs.frame?.minY ?? .greatestFiniteMagnitude
            if lhsY == rhsY {
                let lhsX = lhs.frame?.minX ?? .greatestFiniteMagnitude
                let rhsX = rhs.frame?.minX ?? .greatestFiniteMagnitude
                return lhsX < rhsX
            }
            return lhsY < rhsY
        }

        if sortedRows.isEmpty {
            print("Row summary: no AXRow elements found.")
            return
        }

        print("Row summary (\(sortedRows.count) rows):")
        for (index, row) in sortedRows.enumerated() {
            if let range, !range.contains(index) {
                continue
            }

            let summary = summarizeRow(row)
            var fields: [String] = []
            fields.append("row=\(index)")
            fields.append("frame=\(frameDescription(row.frame))")
            fields.append("cells=\(summary.cellCount)")
            fields.append("textAreas=\(summary.textAreaCount)")
            fields.append("staticTexts=\(summary.staticTextCount)")
            fields.append("links=\(summary.linkCount)")
            fields.append("images=\(summary.imageCount)")
            fields.append("buttons=\(summary.buttonCount)")
            if !summary.timeCandidates.isEmpty {
                fields.append("time=\(summary.timeCandidates.joined(separator: "|"))")
            }
            if !summary.authorCandidates.isEmpty {
                fields.append("authorCandidates=\(summary.authorCandidates.joined(separator: "|"))")
            }
            if !summary.buttonTitles.isEmpty {
                fields.append("buttonTitles=\(summary.buttonTitles.joined(separator: "|"))")
            }
            if effectiveShowPath {
                fields.append("path=\(compactPath(for: row))")
            }
            print("  [\(fields.joined(separator: ", "))]")
        }
    }

    private struct RowQuickSummary {
        let cellCount: Int
        let textAreaCount: Int
        let staticTextCount: Int
        let linkCount: Int
        let imageCount: Int
        let buttonCount: Int
        let timeCandidates: [String]
        let authorCandidates: [String]
        let buttonTitles: [String]
    }

    private func summarizeRow(_ row: UIElement) -> RowQuickSummary {
        let directCells = row.children.filter { $0.role == kAXCellRole }
        let containers = directCells.isEmpty ? [row] : directCells

        var textAreaCount = 0
        var staticTextCount = 0
        var linkCount = 0
        var imageCount = 0
        var buttonCount = 0
        var tokens: [String] = []
        var buttonTitles: [String] = []

        for container in containers {
            let textAreas = container.findAll(role: kAXTextAreaRole, limit: 8, maxNodes: 120)
            textAreaCount += textAreas.count

            let staticTexts = container.findAll(role: kAXStaticTextRole, limit: 20, maxNodes: 180)
            staticTextCount += staticTexts.count
            for staticText in staticTexts {
                let normalized = normalizeText(staticText.stringValue)
                guard !normalized.isEmpty else { continue }
                tokens.append(contentsOf: metadataTokens(from: normalized))
            }

            let links = container.findAll(role: kAXLinkRole, limit: 8, maxNodes: 120)
            linkCount += links.count

            let images = container.findAll(role: kAXImageRole, limit: 8, maxNodes: 120)
            imageCount += images.count

            let buttons = container.findAll(role: kAXButtonRole, limit: 12, maxNodes: 160)
            buttonCount += buttons.count
            for button in buttons {
                let title = normalizeText(button.title)
                guard !title.isEmpty else { continue }
                buttonTitles.append(title)
            }
        }

        let uniqueTokens = deduplicate(tokens)
        let uniqueButtonTitles = deduplicate(buttonTitles)

        var timeCandidates: [String] = []
        var authorCandidates: [String] = []
        for token in uniqueTokens {
            if let time = extractTimeToken(from: token) {
                timeCandidates.append(time)
                continue
            }
            if isLikelyCountToken(token) || isLikelySystemMetadataToken(token) {
                continue
            }
            authorCandidates.append(token)
        }

        return RowQuickSummary(
            cellCount: directCells.count,
            textAreaCount: textAreaCount,
            staticTextCount: staticTextCount,
            linkCount: linkCount,
            imageCount: imageCount,
            buttonCount: buttonCount,
            timeCandidates: deduplicate(timeCandidates).prefix(3).map { $0 },
            authorCandidates: deduplicate(authorCandidates).prefix(3).map { $0 },
            buttonTitles: uniqueButtonTitles.prefix(3).map { $0 }
        )
    }

    private func compactPath(for element: UIElement, maxHops: Int = 20) -> String {
        var segments: [String] = []
        var cursor: UIElement? = element
        var hops = 0

        while let node = cursor, hops < maxHops {
            let role = node.role ?? "AXUnknown"
            let indexInParent: Int
            if let parent = node.parent {
                indexInParent = parent.children.firstIndex(where: { sibling in
                    CFEqual(sibling.axElement, node.axElement)
                }) ?? 0
            } else {
                indexInParent = 0
            }
            segments.append("\(role)[\(indexInParent)]")
            cursor = node.parent
            hops += 1
        }

        return segments.reversed().joined(separator: "/")
    }

    private func frameDescription(_ frame: CGRect?) -> String {
        guard let frame else { return "unknown" }
        return "x=\(Int(frame.origin.x)) y=\(Int(frame.origin.y)) w=\(Int(frame.size.width)) h=\(Int(frame.size.height))"
    }

    private func normalizeText(_ text: String?) -> String {
        guard let text else { return "" }
        return text
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func metadataTokens(from text: String) -> [String] {
        text
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private func deduplicate(_ values: [String]) -> [String] {
        var seen = Set<String>()
        var unique: [String] = []
        unique.reserveCapacity(values.count)

        for value in values {
            guard !value.isEmpty else { continue }
            if seen.contains(value) { continue }
            seen.insert(value)
            unique.append(value)
        }
        return unique
    }

    private func extractTimeToken(from token: String) -> String? {
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        if let meridiemRange = trimmed.range(
            of: #"(오전|오후)\s*([1-9]|1[0-2]):[0-5][0-9]"#,
            options: .regularExpression
        ) {
            return String(trimmed[meridiemRange])
        }

        let parts = trimmed.split(whereSeparator: \.isWhitespace)
        for part in parts {
            let normalized = String(part).trimmingCharacters(in: .punctuationCharacters)
            if normalized.range(
                of: #"^([01]?[0-9]|2[0-3]):[0-5][0-9]$"#,
                options: .regularExpression
            ) != nil {
                return normalized
            }
        }

        return nil
    }

    private func isLikelyCountToken(_ token: String) -> Bool {
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        return trimmed.unicodeScalars.allSatisfy { CharacterSet.decimalDigits.contains($0) }
    }

    private func isLikelySystemMetadataToken(_ token: String) -> Bool {
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }

        if trimmed.range(of: #"^\d{4}-\d{2}-\d{2}"#, options: .regularExpression) != nil {
            return true
        }
        if trimmed.range(of: #"^\d{4}[./-]\d{1,2}[./-]\d{1,2}"#, options: .regularExpression) != nil {
            return true
        }
        if trimmed.range(of: #"^\d{1,2}월\s*\d{1,2}일"#, options: .regularExpression) != nil {
            return true
        }
        return false
    }
}
