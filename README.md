```shell
    uv venv
```

```shell
    uv sync
```

```shell
    ruff check . --fix --unsafe-fixes
```

```shell
    ruff format .
```

Fill in .env and then:
```shell
    python telia_ripper.py
```

Make sure you have your .venv activated for all of this to work.

Paste this into your browser console and click Play to capture the PSSH:

```javascript
const originalGenerateRequest = MediaKeySession.prototype.generateRequest;

MediaKeySession.prototype.generateRequest = function(initDataType, initData) {
    if (initData instanceof ArrayBuffer) {
        const uint8Array = new Uint8Array(initData);
        const base64 = btoa(String.fromCharCode.apply(null, uint8Array));
        
        console.log('initData (base64):', base64);
    }
    
    return originalGenerateRequest.call(this, initDataType, initData);
};
```