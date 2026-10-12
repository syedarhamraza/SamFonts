plugins {
    alias(libs.plugins.android.application)
}

android {
    // Watch Face Format watch faces contain no code, only resources.
    enableKotlin = false
    namespace = "com.syedarhamraza.pulsering"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.syedarhamraza.pulsering"
        // Weather data needs Watch Face Format v2 = Wear OS 5 (API 34).
        // Galaxy Watch 7 ships with Wear OS 5, so this covers it.
        minSdk = 34
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
    }

    buildTypes {
        debug {
            isMinifyEnabled = true
        }
        release {
            isMinifyEnabled = true
            // Keep all resources: they are referenced from watchface.xml,
            // which the resource shrinker cannot see.
            isShrinkResources = false
            // Replace with your own signing config before uploading to Play.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}
