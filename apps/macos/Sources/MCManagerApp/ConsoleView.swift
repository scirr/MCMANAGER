import MCManagerKit
import SwiftUI

struct ConsoleView: View {
    @Bindable var model: ConsoleViewModel

    var body: some View {
        VStack(spacing: 8) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(model.lines.enumerated()), id: \.offset) { _, line in
                            Text(verbatim: line)
                                .font(.system(.caption, design: .monospaced))
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .padding(8)
                }
                .background(.background.secondary)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .onChange(of: model.lines.count) {
                    if model.lines.count > 0 {
                        proxy.scrollTo(model.lines.count - 1, anchor: .bottom)
                    }
                }
            }
            HStack {
                TextField(tr("Command"), text: $model.commandText)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await model.send() } }
                Button {
                    Task { await model.send() }
                } label: {
                    Label(tr("Send"), systemImage: "paperplane.fill")
                }
                .help(tr("Send"))
                .accessibilityLabel(tr("Send the command"))
                .disabled(model.commandText.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(.top, 8)
    }
}
