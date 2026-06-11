import SwiftUI

/// 카운터 값을 보여주고 증감 버튼을 제공하는 화면.
///
/// `CounterViewModel`을 구독해 상태를 그린다. 이 파일도 HES Swift 게이트를
/// 그대로 통과하는 깨끗한 예시다.
struct CounterView: View {
    @StateObject private var viewModel = CounterViewModel()

    var body: some View {
        VStack(spacing: 24) {
            Text("\(viewModel.count)")
                .font(.largeTitle)
                .monospacedDigit()

            HStack(spacing: 16) {
                Button("−") { viewModel.decrement() }
                Button("Reset") { viewModel.reset() }
                Button("+") { viewModel.increment() }
            }
            .buttonStyle(.borderedProminent)
        }
        .padding()
    }
}

#Preview {
    CounterView()
}
