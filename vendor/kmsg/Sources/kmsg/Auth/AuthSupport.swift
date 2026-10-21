import Foundation

enum AuthBootstrap {
    @discardableResult
    static func requireAuthenticated(traceAX: Bool) throws -> KakaoTalkApp {
        // Work bridge never stores, reads, or enters login credentials.
        let kakao = try KakaoTalkApp(autoLaunch: false)
        guard kakao.chatListWindow != nil else {
            throw KakaoTalkError.actionFailed("Business KakaoTalk must already be logged in with its chat list visible")
        }
        return kakao
    }
}
