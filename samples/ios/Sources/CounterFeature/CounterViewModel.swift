import Foundation
import os

/// 카운터 화면의 상태와 동작을 담는 뷰모델.
///
/// HES Swift 게이트를 통과하는 깨끗한 예시다. 콘솔 출력·강제 캐스트·강제 try·
/// 강제 언래핑을 쓰지 않고, 진단 로그는 Logger 로 남긴다.
@MainActor
final class CounterViewModel: ObservableObject {
    @Published private(set) var count: Int = 0

    private let logger = Logger(subsystem: "com.hooni.hes.sample", category: "Counter")

    func increment() {
        count += 1
        logger.debug("count incremented to \(self.count, privacy: .public)")
    }

    func decrement() {
        guard count > 0 else { return }
        count -= 1
        logger.debug("count decremented to \(self.count, privacy: .public)")
    }

    func reset() {
        count = 0
        logger.debug("count reset")
    }
}
