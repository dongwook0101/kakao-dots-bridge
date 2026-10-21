import ArgumentParser
import ApplicationServices.HIServices
import Foundation

struct SendCommand: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "send",
        abstract: "Send a message to a chat",
        discussion: """
            Use either:
              kmsg send <recipient> <message>
              kmsg send --chat-id <chat-id> <message>
            """
    )

    @Option(name: .long, help: "Send using a chat_id from 'kmsg chats'")
    var chatID: String?

    @Argument(help: "Recipient name, or message when --chat-id is used")
    var firstValue: String?

    @Argument(help: "Message to send when recipient is provided")
    var secondValue: String?

    @Flag(name: .long, help: "Don't actually send, just show what would happen")
    var dryRun: Bool = false

    @Flag(name: .long, help: "Show AX traversal and retry details")
    var traceAX: Bool = false

    @Flag(name: .long, help: "Disable AX path cache for this run")
    var noCache: Bool = false

    @Flag(name: .long, help: "Rebuild AX path cache for this run")
    var refreshCache: Bool = false

    @Flag(name: [.short, .long], help: "Keep chat and list windows open after sending message")
    var keepWindow: Bool = false

    @Flag(
        name: .long,
        help: ArgumentHelp(
            "Enable deep window recovery when fast window detection fails",
            visibility: .default
        )
    )
    var deepRecovery: Bool = false

    private enum SendFailureCode: String {
        case focusFail = "FOCUS_FAIL"
        case inputNotReflected = "INPUT_NOT_REFLECTED"
        case enterNotEffective = "ENTER_NOT_EFFECTIVE"
        case forcedTypingFailed = "FORCED_TYPING_FAILED"
    }

    var recipient: String? {
        guard chatID == nil else { return nil }
        return firstValue
    }

    var message: String {
        if chatID == nil {
            return secondValue ?? ""
        }
        return firstValue ?? ""
    }

    private var targetDescription: String {
        if let chatID {
            return "chat_id '\(chatID)'"
        }
        return "'\(recipient ?? "")'"
    }

    func validate() throws {
        if let chatID, !chatID.isEmpty {
            guard let firstValue, !firstValue.isEmpty else {
                throw ValidationError("Message is required when using --chat-id.")
            }
            guard secondValue == nil else {
                throw ValidationError("Recipient cannot be provided together with --chat-id.")
            }
            return
        }

        guard let firstValue, !firstValue.isEmpty else {
            throw ValidationError("Recipient is required.")
        }
        guard let secondValue, !secondValue.isEmpty else {
            throw ValidationError("Message is required.")
        }
    }

    func run() throws {
        if dryRun {
            print("Dry run mode - no message will be sent")
            if let chatID {
                print("Chat ID: \(chatID)")
            } else {
                print("Recipient: \(recipient ?? "")")
            }
            print("Message: \(message)")
            if keepWindow {
                print("Option: keep auto-opened window")
            }
            return
        }

        guard AccessibilityPermission.ensureGranted(autoPrompt: false, openSettingsOnFailure: false) else {
            AccessibilityPermission.printInstructions()
            throw ExitCode.failure
        }

        let runner = AXActionRunner(traceEnabled: traceAX)

        prepareCacheIfNeeded(runner: runner)
        let kakao = try AuthBootstrap.requireAuthenticated(traceAX: traceAX)
        let chatWindowResolver = ChatWindowResolver(
            kakao: kakao,
            runner: runner,
            useCache: !noCache,
            deepRecoveryEnabled: deepRecovery
        )

        do {
            runner.log("window strategy: focusedWindow -> mainWindow -> windows.first")
            let resolution: ChatWindowResolution
            if let chatID {
                print("Looking for chat with \(targetDescription)...")
                resolution = try chatWindowResolver.resolve(chatID: chatID)
                if resolution.openedTransiently {
                    print("No existing chat window. Opening via chat list or search...")
                } else {
                    print("Found existing chat window.")
                }
            } else {
                let recipient = recipient ?? ""
                print("Looking for chat with \(targetDescription)...")
                resolution = try chatWindowResolver.resolve(query: recipient)
                if resolution.openedTransiently {
                    print("No existing chat window. Opening via search...")
                } else {
                    print("Found existing chat window.")
                }
            }

            try sendMessageToWindow(resolution.window, kakao: kakao, runner: runner)
            closeWindowsIfNeeded(
                resolution: resolution,
                kakao: kakao,
                resolver: chatWindowResolver,
                runner: runner
            )
        } catch {
            print("Failed to send message: \(error)")
            throw ExitCode.failure
        }
    }

    private func supportsAction(_ action: String, on element: UIElement) -> Bool {
        guard let actions = try? element.actionNames() else { return false }
        return actions.contains(action)
    }

    private func prepareCacheIfNeeded(runner: AXActionRunner) {
        guard !noCache, refreshCache else { return }
        do {
            try AXPathCacheStore.shared.clear(slots: [.searchField, .messageInput])
            runner.log("cache: refresh requested, cleared send slots")
        } catch {
            runner.log("cache: refresh clear failed (\(error))")
        }
    }

    private func resolveCachedElement(
        slot: AXPathSlot,
        root: UIElement,
        runner: AXActionRunner,
        validate: (UIElement) -> Bool
    ) -> UIElement? {
        guard !noCache, !refreshCache else { return nil }
        return AXPathCacheStore.shared.resolve(
            slot: slot,
            root: root,
            validate: validate,
            trace: { message in
                runner.log(message)
            }
        )
    }

    private func rememberCachedElement(slot: AXPathSlot, root: UIElement, element: UIElement, runner: AXActionRunner) {
        guard !noCache else { return }
        AXPathCacheStore.shared.remember(
            slot: slot,
            root: root,
            element: element,
            trace: { message in
                runner.log(message)
            }
        )
    }

    private func invalidateCachedSlots(_ slots: [AXPathSlot], runner: AXActionRunner) {
        guard !noCache else { return }
        do {
            try AXPathCacheStore.shared.clear(slots: slots)
            runner.log("cache: invalidated slots=\(slots.map(\.rawValue).joined(separator: ","))")
        } catch {
            runner.log("cache: invalidation failed (\(error))")
        }
    }

    private func isLikelyMessageInputElement(_ element: UIElement, in window: UIElement? = nil) -> Bool {
        guard element.isEnabled else { return false }
        let role = element.role ?? ""
        if role == kAXTextAreaRole {
            return true
        }

        let editable: Bool = element.attributeOptional(kAXEditableAttribute) ?? false
        guard editable else { return false }
        guard role != kAXStaticTextRole && role != kAXImageRole else { return false }
        if role == kAXTextFieldRole && isLikelySearchField(element, in: window) {
            return false
        }
        return true
    }

    private func isLikelySearchField(_ element: UIElement, in window: UIElement?) -> Bool {
        let role = element.role ?? ""
        guard role == kAXTextFieldRole else { return false }

        let joinedText = [
            element.identifier ?? "",
            element.title ?? "",
            element.axDescription ?? "",
        ]
        .joined(separator: " ")
        .lowercased()

        if joinedText.contains("search") || joinedText.contains("검색") {
            return true
        }

        guard let windowFrame = window?.frame, let elementFrame = element.frame, windowFrame.height > 0 else {
            return false
        }

        // If a text field sits outside the target chat window bounds, treat it as non-chat input.
        // This blocks accidental selection of sidebar/global search fields.
        if !isElementLikelyInsideWindow(elementFrame: elementFrame, windowFrame: windowFrame) {
            return true
        }

        let relativeY = (elementFrame.midY - windowFrame.minY) / windowFrame.height
        return relativeY < 0.5
    }

    private func sendMessageToWindow(_ window: UIElement, kakao: KakaoTalkApp, runner: AXActionRunner) throws {
        // Bring KakaoTalk to front so CGEvent key events (Enter) are delivered to KakaoTalk, not the terminal
        kakao.activate()
        _ = tryRaiseWindow(window, runner: runner)
        Thread.sleep(forTimeInterval: 0.1)

        guard window.title == recipient else {
            throw KakaoTalkError.actionFailed("Exact business chat title mismatch; refusing send")
        }
        guard let input = window.findAll(where: { element in
            var settable: DarwinBoolean = false
            return element.role == kAXTextAreaRole &&
                AXUIElementIsAttributeSettable(element.axElement, kAXValueAttribute as CFString, &settable) == .success && settable.boolValue
        }, limit: 10, maxNodes: 300).filter({ candidate in
            guard let wf = window.frame, let ef = candidate.frame else { return false }
            return wf.intersects(ef) && ef.midY > wf.midY
        }).last else {
            throw KakaoTalkError.actionFailed("Business chat input not found; no fallback typing")
        }
        guard (input.stringValue ?? "").isEmpty else {
            throw KakaoTalkError.actionFailed("Existing unsent draft in KakaoTalk; refusing overwrite")
        }
        guard runner.focusWithVerification(input, label: "message input", attempts: 1) else {
            throw KakaoTalkError.actionFailed("[\(SendFailureCode.focusFail.rawValue)] Could not focus message input")
        }

        let inputReady =
            runner.setTextWithVerification(message, on: input, label: "message input", attempts: 1)
        guard inputReady else {
            throw KakaoTalkError.actionFailed("[\(SendFailureCode.inputNotReflected.rawValue)] Message input was not reflected")
        }

        let sendSucceeded = runner.pressEnterWithVerification(
            on: input,
            label: "message input",
            attempts: 1,
            reflectionTimeout: 0.24,
            retryDelay: 0.06
        )
        guard sendSucceeded else {
            invalidateCachedSlots([.messageInput], runner: runner)
            throw KakaoTalkError.actionFailed("[\(SendFailureCode.enterNotEffective.rawValue)] Enter key had no visible effect")
        }

        print("✓ Message sent to \(targetDescription)")
    }

    private func closeWindowsIfNeeded(
        resolution: ChatWindowResolution,
        kakao: KakaoTalkApp,
        resolver: ChatWindowResolver,
        runner: AXActionRunner
    ) {
        guard !keepWindow else {
            runner.log("send: keep-window enabled; skipping auto-close")
            return
        }

        if resolver.closeWindow(resolution.window) {
            print("✓ Chat window closed.")
        } else {
            runner.log("send: close window could not be verified")
        }

        if let listWindow = kakao.chatListWindow,
           !areSameAXElement(listWindow, resolution.window)
        {
            if resolver.closeWindow(listWindow) {
                runner.log("send: chat list window closed")
            } else {
                runner.log("send: chat list window could not be verified")
            }
        }
    }

    private func resolveMessageInputField(chatWindow: UIElement, kakao: KakaoTalkApp, runner: AXActionRunner) -> UIElement? {
        if let cachedInput = resolveCachedElement(
            slot: .messageInput,
            root: chatWindow,
            runner: runner,
            validate: { candidate in
                isLikelyMessageInputElement(candidate, in: chatWindow)
            }
        ) {
            return cachedInput
        }

        if let focusedElement = kakao.applicationElement.focusedUIElement {
            let focusedCandidates = collectFocusedElementLineageCandidates(focusedElement)
            runner.log("message input fast path: focused lineage candidates=\(focusedCandidates.count)")
            if let input = pickMessageInputField(from: focusedCandidates, in: chatWindow) {
                runner.log("message input fast path resolved: role='\(input.role ?? "unknown")' title='\(input.title ?? "")'")
                rememberCachedElement(slot: .messageInput, root: chatWindow, element: input, runner: runner)
                return input
            }
        }

        for attempt in 1...2 {
            var candidates: [UIElement] = []

            if let focusedWindow = kakao.focusedWindow {
                let focusedWindowCandidates = collectMessageInputCandidates(from: focusedWindow, limit: attempt == 1 ? 36 : 60)
                candidates.append(contentsOf: focusedWindowCandidates)
                runner.log("message input search attempt \(attempt): focusedWindow candidates=\(focusedWindowCandidates.count)")

                if !areSameAXElement(focusedWindow, chatWindow) {
                    let chatWindowCandidates = collectMessageInputCandidates(from: chatWindow, limit: attempt == 1 ? 36 : 60)
                    candidates.append(contentsOf: chatWindowCandidates)
                    runner.log("message input search attempt \(attempt): chatWindow candidates=\(chatWindowCandidates.count)")
                }
            } else {
                let chatWindowCandidates = collectMessageInputCandidates(from: chatWindow, limit: attempt == 1 ? 36 : 60)
                candidates.append(contentsOf: chatWindowCandidates)
                runner.log("message input search attempt \(attempt): chatWindow candidates=\(chatWindowCandidates.count)")
            }

            if let focusedElement = kakao.applicationElement.focusedUIElement {
                let focusedCandidates = collectFocusedElementLineageCandidates(focusedElement)
                candidates.append(contentsOf: focusedCandidates)
                runner.log("message input search attempt \(attempt): focused lineage candidates=\(focusedCandidates.count)")
            }

            if attempt > 1 {
                let appCandidates = collectMessageInputCandidates(from: kakao.applicationElement, limit: 60)
                candidates.append(contentsOf: appCandidates)
                runner.log("message input search attempt \(attempt): app-wide candidates=\(appCandidates.count)")
            }

            if let input = pickMessageInputField(from: deduplicateCandidates(candidates), in: chatWindow) {
                runner.log("message input resolved on attempt \(attempt): role='\(input.role ?? "unknown")' title='\(input.title ?? "")'")
                rememberCachedElement(slot: .messageInput, root: chatWindow, element: input, runner: runner)
                return input
            }

            runner.log("message input search attempt \(attempt): no candidate resolved; reactivating chat window")
            kakao.activate()
            _ = runner.focusWithVerification(chatWindow, label: "chat window", attempts: 1)
            Thread.sleep(forTimeInterval: 0.05)
        }

        let appCandidates = collectMessageInputCandidates(from: kakao.applicationElement, limit: 90)
        runner.log("message input final fallback: app-wide candidates=\(appCandidates.count)")
        if let input = pickMessageInputField(from: deduplicateCandidates(appCandidates), in: chatWindow) {
            rememberCachedElement(slot: .messageInput, root: chatWindow, element: input, runner: runner)
            return input
        }
        return nil
    }

    private func collectMessageInputCandidates(from root: UIElement, limit: Int = 80) -> [UIElement] {
        let nodeBudget = max(200, limit * 4)
        let roleCandidates = root.findAll(where: { element in
            guard element.isEnabled else { return false }
            return element.role == kAXTextAreaRole || element.role == kAXTextFieldRole
        }, limit: limit, maxNodes: nodeBudget)

        let editableCandidates = root.findAll(where: { element in
            guard element.isEnabled else { return false }
            let editable: Bool = element.attributeOptional(kAXEditableAttribute) ?? false
            guard editable else { return false }
            let role = element.role ?? ""
            return role != kAXStaticTextRole && role != kAXImageRole
        }, limit: limit, maxNodes: nodeBudget)

        return roleCandidates + editableCandidates
    }

    private func collectFocusedElementLineageCandidates(_ focusedElement: UIElement) -> [UIElement] {
        var candidates: [UIElement] = [focusedElement]
        var cursor: UIElement? = focusedElement.parent
        var hops = 0

        while let element = cursor, hops < 4 {
            candidates.append(element)
            let textDescendants = element.findAll(where: { node in
                guard node.isEnabled else { return false }
                return node.role == kAXTextAreaRole || node.role == kAXTextFieldRole
            }, limit: 8, maxNodes: 48)
            candidates.append(contentsOf: textDescendants)
            cursor = element.parent
            hops += 1
        }

        return candidates
    }

    private func deduplicateCandidates(_ candidates: [UIElement]) -> [UIElement] {
        var unique: [UIElement] = []
        unique.reserveCapacity(candidates.count)
        for candidate in candidates {
            if unique.contains(where: { areSameAXElement($0, candidate) }) {
                continue
            }
            unique.append(candidate)
        }
        return unique
    }

    private func areSameAXElement(_ lhs: UIElement, _ rhs: UIElement) -> Bool {
        CFEqual(lhs.axElement, rhs.axElement)
    }

    private func forceTypeIntoChatWindow(chatWindow: UIElement, kakao: KakaoTalkApp, runner: AXActionRunner) -> Bool {
        runner.log("fallback: force typing mode enabled")

        kakao.activate()
        _ = tryRaiseWindow(chatWindow, runner: runner)
        Thread.sleep(forTimeInterval: 0.12)

        _ = runner.focusWithVerification(chatWindow, label: "chat window fallback", attempts: 1)
        runner.log("fallback: typing into active chat window")
        _ = runner.typeTextWithVerification(message, on: nil, label: "forced typing", attempts: 1)
        runner.pressEnterKey()
        Thread.sleep(forTimeInterval: 0.08)
        return true
    }

    private func tryRaiseWindow(_ window: UIElement, runner: AXActionRunner) -> Bool {
        if supportsAction(kAXRaiseAction, on: window) {
            do {
                try window.performAction(kAXRaiseAction)
                runner.log("fallback: window raised via AXRaise")
                return true
            } catch {
                runner.log("fallback: AXRaise failed (\(error))")
            }
        }
        return false
    }

    private func pickMessageInputField(from fields: [UIElement], in window: UIElement) -> UIElement? {
        fields.sorted { lhs, rhs in
            let lhsScore = scoreMessageInputCandidate(lhs, in: window)
            let rhsScore = scoreMessageInputCandidate(rhs, in: window)
            return lhsScore > rhsScore
        }
        .first
    }

    private func scoreMessageInputCandidate(_ element: UIElement, in window: UIElement) -> Double {
        if !isLikelyMessageInputElement(element, in: window) {
            return -Double.greatestFiniteMagnitude
        }

        let role = element.role ?? ""
        let roleScore: Double
        if role == kAXTextAreaRole {
            roleScore = 12_000.0
        } else if role == kAXTextFieldRole {
            roleScore = 9_000.0
        } else {
            let editable: Bool = element.attributeOptional(kAXEditableAttribute) ?? false
            roleScore = editable ? 6_000.0 : 0.0
        }
        let yScore = Double(element.position?.y ?? 0)
        let topPenalty: Double
        if role == kAXTextFieldRole, isLikelySearchField(element, in: window) {
            topPenalty = 8_000.0
        } else {
            topPenalty = 0.0
        }
        let locationScore: Double
        if let windowFrame = window.frame, let elementFrame = element.frame {
            if isElementLikelyInsideWindow(elementFrame: elementFrame, windowFrame: windowFrame) {
                let relativeY = (elementFrame.midY - windowFrame.minY) / max(windowFrame.height, 1.0)
                locationScore = relativeY > 0.55 ? 1_500.0 : 0.0
            } else {
                locationScore = -6_000.0
            }
        } else {
            locationScore = 0.0
        }
        let sizeScore = Double(element.size?.height ?? 0)
        let focusScore = element.isFocused ? 2_000.0 : 0.0
        return roleScore + yScore + sizeScore + focusScore + locationScore - topPenalty
    }

    private func isElementLikelyInsideWindow(elementFrame: CGRect, windowFrame: CGRect) -> Bool {
        let expandedWindow = windowFrame.insetBy(dx: -24, dy: -24)
        return expandedWindow.intersects(elementFrame)
    }
}
