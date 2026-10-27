import UIKit

/// Intentionally broken for iPhone Duo. Tagged lines are scan fixtures.
/// Note: there is deliberately no viewDidLayoutSubviews in this file.
final class FeedViewController: UIViewController {

    private let imageView = UIImageView()
    private let toolbar = UIToolbar() // duo: custom-bar-class
    private var cardWidth: CGFloat = 0
    private let pixelScale = UIScreen.main.scale // duo: screen-main-scale

    override func viewDidLoad() {
        super.viewDidLoad()
        let width = view.bounds.width // duo: layout-once
        cardWidth = (width - 32) / 2
        imageView.contentMode = .scaleAspectFill // duo: fill-media
        navigationItem.rightBarButtonItem = UIBarButtonItem(title: "Done", style: .done, target: self, action: #selector(done)) // duo: toolbar-item-no-symbol
        let more = UIBarButtonItem(image: UIImage(systemName: "ellipsis.circle"), style: .plain, target: self, action: #selector(more)) // duo: custom-overflow-menu
        navigationItem.leftBarButtonItem = more
        view.addSubview(toolbar)
        view.addSubview(imageView)
    }

    private func configureColumns() {
        if UIDevice.current.userInterfaceIdiom == .pad { // duo: idiom-check
            cardWidth = 300
        }
        if UIDevice.current.orientation.isLandscape { // duo: orientation-layout
            cardWidth = 240
        }
        if view.bounds.height == 844 { // duo: hardcoded-size
            cardWidth = 171
        }
        let knownWidths: [CGFloat] = [320, 375, 414, 430] // duo: hardcoded-size
        _ = knownWidths
        let side = max(view.safeAreaInsets.left, view.safeAreaInsets.right) // duo: symmetric-safe-area
        imageView.frame = CGRect(x: side, y: 0, width: cardWidth, height: 200)
    }

    @objc private func done() {}
    @objc private func more() {}

    private func legacyCardWidth() -> CGFloat {
        return UIScreen.main.bounds.width / 2 // duo: screen-main-bounds
    }
}
