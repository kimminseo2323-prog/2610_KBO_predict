from kbo_predict import MODEL_VERSION, KST
def test_package_imports():
    assert MODEL_VERSION == "v0.3"
    assert KST.key == "Asia/Seoul"
