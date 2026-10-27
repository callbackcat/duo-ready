import SwiftUI

/// Intentionally broken SwiftUI view for iPhone Duo. Tagged lines are scan fixtures.
struct PlayerView: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var regions: [ReservedRegion] = []
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let isPad = horizontalSizeClass == .regular // duo: regular-means-ipad
        GeometryReader { proxy in
            VStack {
                if horizontalSizeClass == .regular { // duo: regular-width-assumes-regular-height
                    Text("Two columns")
                }
                let columns = Array(repeating: GridItem(.flexible()), count: 3) // duo: centered-grid-odd-columns
                LazyVGrid(columns: columns) {
                    ForEach(0..<9, id: \.self) { Text("\($0)") }
                }
                Image("hero")
                    .resizable()
                    .aspectRatio(contentMode: .fill) // duo: fill-media
                Menu {
                    Button("Share") {}
                } label: {
                    Image(systemName: "ellipsis.circle") // duo: custom-overflow-menu
                }
            }
            .onAppear {
                self.regions = proxy.reservedRegions(kind: .division) // duo: cached-reserved-regions
            }
            .padding(.horizontal, isPad ? 40 : 16)
        }
        .toolbar {
            ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } // duo: toolbar-item-no-symbol
        }
    }
}
