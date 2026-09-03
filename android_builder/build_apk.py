"""
Android Native Companion APK Build Pipeline
Compiles and packages the native Android application wrapper using headless toolchain components (AAPT2, D8/R8, and APKSigner).
"""

import os
import sys
import shutil
import subprocess
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDER_DIR = os.path.join(BASE_DIR, 'android_builder')
SRC_DIR = os.path.join(BUILDER_DIR, 'app_src')

AAPT2 = os.path.join(BUILDER_DIR, 'aapt2.exe')
R8_JAR = os.path.join(BUILDER_DIR, 'r8.jar')
ANDROID_JAR = os.path.join(BUILDER_DIR, 'android.jar')
UBER_SIGNER = os.path.join(BUILDER_DIR, 'uber-apk-signer.jar')

# Locate JDK Java compiler
JAVAC = shutil.which('javac') or (os.path.join(os.environ.get('JAVA_HOME', ''), 'bin', 'javac.exe') if os.environ.get('JAVA_HOME') else r'C:\Program Files\Java\jdk-23\bin\javac.exe')

res_dir = os.path.join(SRC_DIR, 'res')
bin_dir = os.path.join(SRC_DIR, 'bin')
classes_dir = os.path.join(SRC_DIR, 'classes')
gen_dir = os.path.join(SRC_DIR, 'gen')
manifest_file = os.path.join(SRC_DIR, 'AndroidManifest.xml')

# Clean bin, classes, gen only
for d in [bin_dir, classes_dir, gen_dir]:
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)

# 1. Compile resources
print('[Step 1] Compiling resources with aapt2...')
compiled_res_zip = os.path.join(bin_dir, 'compiled_res.zip')
cmd_compile = [AAPT2, 'compile', '--dir', res_dir, '-o', compiled_res_zip]
res = subprocess.run(cmd_compile, capture_output=True, text=True)
assert res.returncode == 0, f'aapt2 compile failed: {res.stderr}'

# 2. Link with API 34
print('[Step 2] Linking with aapt2 targeting API 34...')
unaligned_apk = os.path.join(bin_dir, 'unaligned.apk')
cmd_link = [
    AAPT2, 'link',
    '-I', ANDROID_JAR,
    '--manifest', manifest_file,
    '--java', gen_dir,
    '--min-sdk-version', '26',
    '--target-sdk-version', '34',
    '-o', unaligned_apk,
    compiled_res_zip,
    '--auto-add-overlay'
]
res = subprocess.run(cmd_link, capture_output=True, text=True)
assert res.returncode == 0, f'aapt2 link failed: {res.stderr}'

# 3. Compile Java code
print('[Step 3] Compiling Java code with javac...')
java_sources = []
for d in [os.path.join(SRC_DIR, 'java'), gen_dir]:
    for root, _, files in os.walk(d):
        for f in files:
            if f.endswith('.java'):
                java_sources.append(os.path.join(root, f))

cmd_javac = [
    JAVAC,
    '-cp', ANDROID_JAR,
    '-d', classes_dir,
    '--release', '8'
] + java_sources

res = subprocess.run(cmd_javac, capture_output=True, text=True)
assert res.returncode == 0, f'javac compilation failed: {res.stderr}'

# 4. D8 to classes.dex
print('[Step 4] Compiling classes to DEX with D8...')
compiled_classes = []
for root, _, files in os.walk(classes_dir):
    for f in files:
        if f.endswith('.class'):
            compiled_classes.append(os.path.join(root, f))

cmd_d8 = [
    'java', '-cp', R8_JAR,
    'com.android.tools.r8.D8',
    '--lib', ANDROID_JAR,
    '--output', bin_dir,
    '--min-api', '26'
] + compiled_classes

res = subprocess.run(cmd_d8, capture_output=True, text=True)
assert res.returncode == 0, f'D8 failed: {res.stderr}'
dex_file = os.path.join(bin_dir, 'classes.dex')
assert os.path.exists(dex_file), 'classes.dex not found!'

# 5. Add classes.dex
print('[Step 5] Adding classes.dex to unaligned.apk...')
with zipfile.ZipFile(unaligned_apk, 'a') as z:
    z.write(dex_file, 'classes.dex')

# 6. Sign and align
print('[Step 6] Signing & aligning with uber-apk-signer...')
final_apk_dir = os.path.join(BASE_DIR, 'static', 'downloads')
os.makedirs(final_apk_dir, exist_ok=True)
final_apk = os.path.join(final_apk_dir, 'StudyEdge.apk')

cmd_uber = [
    'java', '-jar', UBER_SIGNER,
    '-a', unaligned_apk,
    '-o', final_apk_dir,
    '--allowResign'
]
res = subprocess.run(cmd_uber, capture_output=True, text=True)
assert res.returncode == 0, f'uber-apk-signer failed: {res.stderr}'

signed_output = os.path.join(final_apk_dir, 'unaligned-aligned-debugSigned.apk')
if os.path.exists(signed_output):
    if os.path.exists(final_apk):
        os.remove(final_apk)
    os.rename(signed_output, final_apk)
    print(f'Renamed signed APK to: {final_apk}')

print('Build SUCCESS! APK size:', os.path.getsize(final_apk), 'bytes')
