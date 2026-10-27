import UIKit

// Intentionally broken for iPhone Duo. Each tagged line is a scan fixture.
// Legacy app-delegate lifecycle: no SceneDelegate anywhere in this target.

@main
class AppDelegate: UIResponder, UIApplicationDelegate {

    var window: UIWindow?
    var screen: UIScreen = UIScreen.main // duo: stored-uiscreen

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        let window = UIWindow(frame: UIScreen.main.bounds) // duo: window-frame-init // duo: screen-main-bounds
        window.rootViewController = UINavigationController(rootViewController: FeedViewController())
        window.makeKeyAndVisible()
        self.window = window
        return true
    }
}
