import UIKit
import SwiftUI

// The same screens written the way Apple recommends for iPhone Duo.
// scan.py must report zero findings for this directory.

final class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }
        let window = UIWindow(windowScene: windowScene)
        window.rootViewController = UINavigationController(rootViewController: FeedViewControllerFixed())
        window.makeKeyAndVisible()
        self.window = window
    }
}

final class FeedViewControllerFixed: UIViewController {

    private let imageView = UIImageView()
    private var cardWidth: CGFloat = 0

    override func viewDidLoad() {
        super.viewDidLoad()
        imageView.contentMode = .scaleAspectFit
        navigationItem.rightBarButtonItem = UIBarButtonItem(title: "Done", image: UIImage(systemName: "checkmark"), target: self, action: #selector(done))
        navigationItem.additionalOverflowItems = UIDeferredMenuElement({ provider in provider([]) })
        view.addSubview(imageView)
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        let content = view.bounds.inset(by: view.safeAreaInsets)
        let twoPane = traitCollection.horizontalSizeClass == .regular && traitCollection.verticalSizeClass == .regular
        cardWidth = twoPane ? content.width / 2 : content.width
        imageView.frame = CGRect(x: content.minX, y: content.minY, width: cardWidth, height: 200)
        _ = traitCollection.displayScale
        _ = view.window?.windowScene?.screen
    }

    override func viewWillTransition(to size: CGSize, with coordinator: UIViewControllerTransitionCoordinator) {
        super.viewWillTransition(to: size, with: coordinator)
        coordinator.animate(alongsideTransition: { _ in self.view.setNeedsLayout() })
    }

    @objc private func done() {}
}

struct PlayerViewFixed: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @Environment(\.verticalSizeClass) private var verticalSizeClass

    var body: some View {
        GeometryReader { proxy in
            let regions = proxy.reservedRegions(kind: .division)
            let twoPane = horizontalSizeClass == .regular && verticalSizeClass == .regular
            let columns = Array(repeating: GridItem(.flexible()), count: twoPane ? 4 : 2)
            VStack {
                LazyVGrid(columns: columns) {
                    ForEach(0..<8, id: \.self) { Text("\($0)") }
                }
                Image("hero")
                    .resizable()
                    .aspectRatio(contentMode: twoPane ? .fit : .fill)
                Text("fold regions: \(regions.count)")
            }
            .padding(.leading, proxy.safeAreaInsets.leading)
            .padding(.trailing, proxy.safeAreaInsets.trailing)
        }
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("Done", systemImage: "checkmark") {}
            }
            ToolbarOverflowMenu {
                Button("Share", systemImage: "square.and.arrow.up") {}
            }
        }
    }
}
