import ApplicationServices.HIServices

/// Provides a human-readable description for AXError codes
public func describeAXError(_ error: AXError) -> String {
    switch error {
    case .success:
        return "Success"
    case .failure:
        return "Generic failure"
    case .illegalArgument:
        return "Illegal argument"
    case .invalidUIElement:
        return "Invalid UI element"
    case .invalidUIElementObserver:
        return "Invalid UI element observer"
    case .cannotComplete:
        return "Cannot complete (app may have terminated)"
    case .attributeUnsupported:
        return "Attribute unsupported"
    case .actionUnsupported:
        return "Action unsupported"
    case .notificationUnsupported:
        return "Notification unsupported"
    case .notImplemented:
        return "Not implemented"
    case .notificationAlreadyRegistered:
        return "Notification already registered"
    case .notificationNotRegistered:
        return "Notification not registered"
    case .apiDisabled:
        return "Accessibility API disabled"
    case .noValue:
        return "No value"
    case .parameterizedAttributeUnsupported:
        return "Parameterized attribute unsupported"
    case .notEnoughPrecision:
        return "Not enough precision"
    @unknown default:
        return "Unknown error (code: \(error.rawValue))"
    }
}

/// Custom error type for Accessibility operations
public enum AccessibilityError: Error, CustomStringConvertible {
    case axError(AXError)
    case typeMismatch
    case noValue

    public var description: String {
        switch self {
        case .axError(let error):
            return describeAXError(error)
        case .typeMismatch:
            return "Type mismatch"
        case .noValue:
            return "No value"
        }
    }
}
