#!/bin/sh
set -eu

REPO_ROOT="${SRCROOT}/../../.."
PYTHON_XCFRAMEWORK="${REPO_ROOT}/plugins/tauri-plugin-mesh-runtime/ios/Frameworks/Python.xcframework"
APP_PACKAGES="${REPO_ROOT}/service/build/ios/app_packages"
PLIST_TEMPLATE="${REPO_ROOT}/scripts/ios-dylib-Info-template.plist"
APP_ROOT="${TARGET_BUILD_DIR}/${WRAPPER_NAME}"
PYTHON_ROOT="${APP_ROOT}/python"

if [ "${EFFECTIVE_PLATFORM_NAME:-}" = "-iphonesimulator" ]; then
    PYTHON_SLICE=$(find "${PYTHON_XCFRAMEWORK}" -maxdepth 1 -type d -name '*simulator*' -print -quit)
else
    PYTHON_SLICE=$(find "${PYTHON_XCFRAMEWORK}" -maxdepth 1 -type d -name 'ios-arm64' -print -quit)
fi
if [ -z "${PYTHON_SLICE}" ] || [ ! -d "${PYTHON_SLICE}/lib" ]; then
    echo "Compatible Python XCFramework slice not found" >&2
    exit 1
fi
if [ ! -d "${APP_PACKAGES}" ]; then
    echo "Run python3 scripts/prepare_ios_runtime.py before building" >&2
    exit 1
fi

mkdir -p "${PYTHON_ROOT}/lib" "${APP_ROOT}/app_packages" "${APP_ROOT}/Frameworks"
rsync -a --delete "${PYTHON_SLICE}/lib/" "${PYTHON_ROOT}/lib/"
rsync -a --delete "${APP_PACKAGES}/" "${APP_ROOT}/app_packages/"

install_dylib() {
    INSTALL_BASE=$1
    FULL_EXT=$2
    RELATIVE_EXT=${FULL_EXT#"${APP_ROOT}/"}
    PYTHON_EXT=${RELATIVE_EXT#"${INSTALL_BASE}"}
    FULL_MODULE_NAME=$(printf '%s' "${PYTHON_EXT}" | cut -d '.' -f 1 | tr '/' '.')
    FRAMEWORK_FOLDER="${APP_ROOT}/Frameworks/${FULL_MODULE_NAME}.framework"
    FRAMEWORK_BINARY="${FRAMEWORK_FOLDER}/${FULL_MODULE_NAME}"
    mkdir -p "${FRAMEWORK_FOLDER}"
    cp "${PLIST_TEMPLATE}" "${FRAMEWORK_FOLDER}/Info.plist"
    plutil -replace CFBundleExecutable -string "${FULL_MODULE_NAME}" "${FRAMEWORK_FOLDER}/Info.plist"
    plutil -replace CFBundleName -string "${FULL_MODULE_NAME}" "${FRAMEWORK_FOLDER}/Info.plist"
    BUNDLE_ID=$(printf '%s' "${PRODUCT_BUNDLE_IDENTIFIER}.${FULL_MODULE_NAME}" | tr '_' '-')
    plutil -replace CFBundleIdentifier -string "${BUNDLE_ID}" "${FRAMEWORK_FOLDER}/Info.plist"
    mv "${FULL_EXT}" "${FRAMEWORK_BINARY}"
    printf '%s\n' "Frameworks/${FULL_MODULE_NAME}.framework/${FULL_MODULE_NAME}" > "${FULL_EXT%.so}.fwork"
    printf '%s\n' "${RELATIVE_EXT%.so}.fwork" > "${FRAMEWORK_BINARY}.origin"
}

PYTHON_VERSION_DIR=$(find "${PYTHON_ROOT}/lib" -maxdepth 1 -type d -name 'python3.*' -print -quit)
if [ -z "${PYTHON_VERSION_DIR}" ]; then
    echo "Python standard library was not copied" >&2
    exit 1
fi
find "${PYTHON_VERSION_DIR}/lib-dynload" -type f -name '*.so' -print | while IFS= read -r extension; do
    install_dylib "python/lib/$(basename "${PYTHON_VERSION_DIR}")/lib-dynload/" "${extension}"
done
find "${APP_ROOT}/app_packages" -type f -name '*.so' -print | while IFS= read -r extension; do
    install_dylib "app_packages/" "${extension}"
done

SIGN_IDENTITY=${EXPANDED_CODE_SIGN_IDENTITY:--}
find "${APP_ROOT}/Frameworks" -type d -name '*.framework' -print | while IFS= read -r framework; do
    /usr/bin/codesign --force --sign "${SIGN_IDENTITY}" ${OTHER_CODE_SIGN_FLAGS:-} \
        --timestamp=none --preserve-metadata=identifier,entitlements,flags \
        --generate-entitlement-der "${framework}"
done
