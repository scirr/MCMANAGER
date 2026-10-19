import Foundation
import Security

final class PinnedSessionDelegate: NSObject, URLSessionDelegate, URLSessionTaskDelegate, @unchecked Sendable {
    private let pinned: String?
    private let lock = NSLock()
    private var seen: String?

    init(pinned: String?) {
        self.pinned = pinned
    }

    var presented: String? {
        lock.lock()
        defer { lock.unlock() }
        return seen
    }

    private func presentedDER(_ trust: SecTrust) -> Data? {
        guard let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate], let leaf = chain.first else { return nil }
        return SecCertificateCopyData(leaf) as Data
    }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust else {
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }
        let der = presentedDER(trust)
        if let der {
            lock.lock()
            seen = Fingerprint.format(der)
            lock.unlock()
        }
        if pinned != nil, Fingerprint.accepts(pinned: pinned, presentedDER: der) {
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            completionHandler(.cancelAuthenticationChallenge, nil)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

func pinnedSession(delegate: PinnedSessionDelegate, timeout: TimeInterval) -> URLSession {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.tlsMinimumSupportedProtocolVersion = .TLSv13
    configuration.connectionProxyDictionary = [:]
    configuration.timeoutIntervalForRequest = timeout
    configuration.timeoutIntervalForResource = 0
    configuration.waitsForConnectivity = false
    configuration.httpCookieStorage = nil
    configuration.urlCache = nil
    return URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
}
