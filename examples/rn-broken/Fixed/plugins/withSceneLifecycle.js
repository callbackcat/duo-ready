// Expo config plugin: adds the UIScene life cycle that apps built with the iOS 27
// SDK need (UIKit kills an AppDelegate-only app 2 s after launch). Registered in
// app.json under "plugins". See references/rules-react-native.md#expo-no-scene-lifecycle.
const { withInfoPlist } = require('expo/config-plugins');

module.exports = function withSceneLifecycle(config) {
  return withInfoPlist(config, (cfg) => {
    cfg.modResults.UIApplicationSceneManifest = {
      UIApplicationSupportsMultipleScenes: false,
      UISceneConfigurations: {
        UIWindowSceneSessionRoleApplication: [
          { UISceneDelegateClassName: '$(PRODUCT_MODULE_NAME).SceneDelegate', UISceneConfigurationName: 'Default' },
        ],
      },
    };
    return cfg;
  });
};
