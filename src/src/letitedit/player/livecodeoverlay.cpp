#include "letitedit/player/livecodeoverlay.h"

#ifdef Q_OS_WIN

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QPainter>
#include <QPolygonF>
#include <QJsonObject>
#include <QRegularExpression>
#include <QUrl>
#include <QDebug>
#include <Mlt.h>
#include "mainwindow.h"
#include "letitedit/chat/aichatpanel.h"
#include <atomic>
#include <QUndoStack>

namespace {

void trace(const QString &message)
{
    const QString path = qEnvironmentVariable("LETITEDIT_LIVE_SCENE_TRACE");
    if (path.isEmpty())
        return;
    QFile file(path);
    if (file.open(QIODevice::WriteOnly | QIODevice::Append))
        file.write((QDateTime::currentDateTime().toString(Qt::ISODateWithMs) + " " + message + "\n").toUtf8());
}

template<class Interface> const IID &handlerId();
template<> const IID &handlerId<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>()
{ return IID_ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler; }
template<> const IID &handlerId<ICoreWebView2CreateCoreWebView2CompositionControllerCompletedHandler>()
{ return IID_ICoreWebView2CreateCoreWebView2CompositionControllerCompletedHandler; }
template<> const IID &handlerId<ICoreWebView2NavigationCompletedEventHandler>()
{ return IID_ICoreWebView2NavigationCompletedEventHandler; }
template<> const IID &handlerId<ICoreWebView2ExecuteScriptCompletedHandler>()
{ return IID_ICoreWebView2ExecuteScriptCompletedHandler; }
template<> const IID &handlerId<ICoreWebView2CapturePreviewCompletedHandler>()
{ return IID_ICoreWebView2CapturePreviewCompletedHandler; }
template<> const IID &handlerId<ICoreWebView2WebResourceRequestedEventHandler>()
{ return IID_ICoreWebView2WebResourceRequestedEventHandler; }

template<class Interface> class HandlerBase : public Interface
{
public:
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void **object) override
    {
        if (iid == IID_IUnknown || iid == handlerId<Interface>()) {
            *object = this;
            AddRef();
            return S_OK;
        }
        *object = nullptr;
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++m_refs; }
    ULONG STDMETHODCALLTYPE Release() override
    {
        const ULONG remaining = --m_refs;
        if (!remaining)
            delete this;
        return remaining;
    }
private:
    std::atomic_ulong m_refs{1};
};

class ControllerDone : public HandlerBase<ICoreWebView2CreateCoreWebView2CompositionControllerCompletedHandler>
{
public:
    explicit ControllerDone(LiveCodeOverlay *overlay) : m_overlay(overlay) {}
    HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, ICoreWebView2CompositionController *controller) override
    {
        if (m_overlay)
            m_overlay->onController(result, controller);
        return S_OK;
    }
private:
    QPointer<LiveCodeOverlay> m_overlay;
};

class EnvironmentDone : public HandlerBase<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>
{
public:
    explicit EnvironmentDone(LiveCodeOverlay *overlay) : m_overlay(overlay) {}
    HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, ICoreWebView2Environment *environment) override
    {
        if (m_overlay)
            m_overlay->onEnvironment(result, environment);
        return S_OK;
    }
private:
    QPointer<LiveCodeOverlay> m_overlay;
};

class ScriptDone : public HandlerBase<ICoreWebView2ExecuteScriptCompletedHandler>
{
public:
    HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, LPCWSTR json) override
    {
        trace(QStringLiteral("script result=%1 json=%2")
            .arg(result).arg(json ? QString::fromWCharArray(json) : QStringLiteral("null")));
        return S_OK;
    }
};

class NavigationDone : public HandlerBase<ICoreWebView2NavigationCompletedEventHandler>
{
public:
    explicit NavigationDone(LiveCodeOverlay *overlay) : m_overlay(overlay) {}
    HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2 *, ICoreWebView2NavigationCompletedEventArgs *args) override
    {
        if (m_overlay)
            m_overlay->onNavigation(args);
        return S_OK;
    }
private:
    QPointer<LiveCodeOverlay> m_overlay;
};

class ResourceRequested : public HandlerBase<ICoreWebView2WebResourceRequestedEventHandler>
{
public:
    explicit ResourceRequested(LiveCodeOverlay *overlay) : m_overlay(overlay) {}
    HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2 *, ICoreWebView2WebResourceRequestedEventArgs *args) override
    {
        if (m_overlay)
            m_overlay->onResourceRequested(args);
        return S_OK;
    }
private:
    QPointer<LiveCodeOverlay> m_overlay;
};

class CaptureDone : public HandlerBase<ICoreWebView2CapturePreviewCompletedHandler>
{
public:
    CaptureDone(IStream *stream, const QString &path) : m_stream(stream), m_path(path) {}
    HRESULT STDMETHODCALLTYPE Invoke(HRESULT result) override
    {
        if (FAILED(result)) {
            trace(QStringLiteral("capture failed=%1").arg(result));
            return S_OK;
        }
        STATSTG stat{};
        if (FAILED(m_stream->Stat(&stat, STATFLAG_NONAME)))
            return S_OK;
        LARGE_INTEGER start{};
        m_stream->Seek(start, STREAM_SEEK_SET, nullptr);
        QByteArray bytes;
        bytes.resize(int(stat.cbSize.QuadPart));
        ULONG read = 0;
        m_stream->Read(bytes.data(), bytes.size(), &read);
        QFile file(m_path);
        if (file.open(QIODevice::WriteOnly))
            file.write(bytes.constData(), read);
        trace(QStringLiteral("capture bytes=%1 path=%2").arg(read).arg(m_path));
        return S_OK;
    }
private:
    Microsoft::WRL::ComPtr<IStream> m_stream;
    QString m_path;
};

class CaptureReviewDone : public HandlerBase<ICoreWebView2CapturePreviewCompletedHandler>
{
public:
    CaptureReviewDone(IStream *stream, QEventLoop *loop, QImage *image)
        : m_stream(stream), m_loop(loop), m_image(image) {}
    HRESULT STDMETHODCALLTYPE Invoke(HRESULT result) override
    {
        if (m_loop && m_image && SUCCEEDED(result)) {
            STATSTG stat{};
            LARGE_INTEGER start{};
            if (SUCCEEDED(m_stream->Stat(&stat, STATFLAG_NONAME))
                && SUCCEEDED(m_stream->Seek(start, STREAM_SEEK_SET, nullptr))) {
                QByteArray bytes;
                bytes.resize(int(stat.cbSize.QuadPart));
                ULONG read = 0;
                if (SUCCEEDED(m_stream->Read(bytes.data(), bytes.size(), &read)))
                    *m_image = QImage::fromData(bytes.left(read), "PNG");
            }
        }
        if (m_loop)
            m_loop->quit();
        return S_OK;
    }
private:
    Microsoft::WRL::ComPtr<IStream> m_stream;
    QPointer<QEventLoop> m_loop;
    QImage *m_image;
};

} // namespace

LiveCodeOverlay::LiveCodeOverlay(QWidget *video, bool review)
    : QObject(video)
    , m_video(video)
    , m_review(review)
{
    m_enabled = qEnvironmentVariable("LETITEDIT_LIVE_SCENES") != QLatin1String("0");
    // The page/range environment variables remain available for isolated
    // composition probes. Real scenes come from the saved timeline item.
    m_page = qEnvironmentVariable("LETITEDIT_LIVE_SCENE_PAGE");
    m_pageInfo.setFile(m_page);
    m_startFrame = qEnvironmentVariableIntValue("LETITEDIT_LIVE_SCENE_START_FRAME");
    m_endFrame = qEnvironmentVariableIntValue("LETITEDIT_LIVE_SCENE_END_FRAME");
    trace(QStringLiteral("constructor enabled=%1 page=%2 range=%3..%4")
        .arg(m_enabled).arg(m_page).arg(m_startFrame).arg(m_endFrame));
    qWarning() << "Live code scene probe" << m_enabled << m_page << m_startFrame << m_endFrame;
    m_pageTimer.setInterval(50);
    connect(&m_pageTimer, &QTimer::timeout, this, [this]() { checkPage(); });
    m_refreshDebounce.setSingleShot(true);
    m_refreshDebounce.setInterval(350);
    connect(&m_refreshDebounce, &QTimer::timeout, this, [this]() { startRefresh(); });
    if (m_enabled)
        m_pageTimer.start();
}

LiveCodeOverlay::~LiveCodeOverlay()
{
    m_pageTimer.stop();
    m_refreshDebounce.stop();
    if (m_refreshProcess)
        m_refreshProcess->kill();
    if (m_fallbackProcess)
        m_fallbackProcess->kill();
    if (m_baseController)
        m_baseController->Close();
    m_webview.Reset();
    m_environment.Reset();
    m_baseController.Reset();
    m_controller.Reset();
    m_target.Reset();
    m_visual.Reset();
    m_composition.Reset();
    m_d3d.Reset();
    if (m_comInitialized)
        CoUninitialize();
    // Keep WebView2Loader loaded until process exit: its asynchronous completion
    // callbacks can still unwind after the host has been removed.
}

LRESULT CALLBACK LiveCodeOverlay::hostProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_NCHITTEST)
        return HTTRANSPARENT;
    if (message == WM_ERASEBKGND)
        return 1;
    return DefWindowProcW(window, message, wparam, lparam);
}

bool LiveCodeOverlay::initialize()
{
    if (m_started || m_failed || !m_video)
        return false;
    m_started = true;
    if (qEnvironmentVariableIntValue("LETITEDIT_LIVE_SCENE_FORCE_FALLBACK") == 1) {
        m_failed = true;
        return false;
    }
    trace(QStringLiteral("initialize"));
    const HRESULT com = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    m_comInitialized = SUCCEEDED(com);
    if (FAILED(com)) {
        qWarning() << "Live code scene: WebView2 needs an STA GUI thread" << Qt::hex << com;
        m_failed = true;
        return false;
    }
    // Attach the DirectComposition visual to the Qt video HWND itself. A child
    // HWND covers the player with an opaque black backing even when WebView2's
    // own page is transparent; the topmost visual on this HWND can blend with
    // the video's swap chain instead. Only this widget becomes native: by default
    // Qt makes its parents and neighbours native too, and the gaps between them
    // show white until they next repaint.
    QCoreApplication::setAttribute(Qt::AA_DontCreateNativeWidgetSiblings);
    m_video->setAttribute(Qt::WA_DontCreateNativeAncestors);
    m_host = reinterpret_cast<HWND>(m_video->winId());
    if (!m_host) {
        qWarning() << "Live code scene: could not create the player surface" << GetLastError();
        m_failed = true;
        return false;
    }
    // A new window shows white until its first frame is presented, about 70 ms over the
    // whole player. Paint it the player's own dark colour straight away.
    if (HDC dc = GetDC(m_host)) {
        RECT area;
        GetClientRect(m_host, &area);
        HBRUSH dark = CreateSolidBrush(RGB(30, 35, 38));
        FillRect(dc, &area, dark);
        DeleteObject(dark);
        ReleaseDC(m_host, dc);
        GdiFlush();
    }
    D3D_FEATURE_LEVEL level;
    HRESULT result = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION,
        m_d3d.GetAddressOf(), &level, nullptr);
    Microsoft::WRL::ComPtr<IDXGIDevice> dxgi;
    if (SUCCEEDED(result))
        result = m_d3d.As(&dxgi);
    if (SUCCEEDED(result))
        result = DCompositionCreateDevice(dxgi.Get(), __uuidof(IDCompositionDevice),
            reinterpret_cast<void **>(m_composition.GetAddressOf()));
    if (SUCCEEDED(result))
        result = m_composition->CreateTargetForHwnd(m_host, TRUE, m_target.GetAddressOf());
    if (SUCCEEDED(result))
        result = m_composition->CreateVisual(m_visual.GetAddressOf());
    if (SUCCEEDED(result))
        result = m_target->SetRoot(m_visual.Get());
    if (SUCCEEDED(result))
        result = m_composition->Commit();
    if (FAILED(result)) {
        qWarning() << "Live code scene: DirectComposition setup failed" << Qt::hex << result;
        m_failed = true;
        return false;
    }
    const QString loaderPath = QCoreApplication::applicationDirPath() + "/WebView2Loader.dll";
    m_loader = LoadLibraryW(reinterpret_cast<const wchar_t *>(loaderPath.utf16()));
    if (!m_loader) {
        qWarning() << "Live code scene: WebView2Loader.dll is missing from" << loaderPath;
        m_failed = true;
        return false;
    }
    using CreateEnvironment = HRESULT (STDAPICALLTYPE *)(PCWSTR, PCWSTR,
        ICoreWebView2EnvironmentOptions *, ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler *);
    auto create = reinterpret_cast<CreateEnvironment>(GetProcAddress(m_loader,
        "CreateCoreWebView2EnvironmentWithOptions"));
    if (!create) {
        m_failed = true;
        return false;
    }
    const QString userData = QDir::tempPath() + "/letitedit-live-scenes-webview2";
    auto done = new EnvironmentDone(this);
    result = create(nullptr, reinterpret_cast<const wchar_t *>(userData.utf16()), nullptr, done);
    done->Release();
    if (FAILED(result)) {
        qWarning() << "Live code scene: WebView2 startup failed" << Qt::hex << result;
        m_failed = true;
        return false;
    }
    updateBounds();
    trace(QStringLiteral("environment requested"));
    return true;
}

void LiveCodeOverlay::onEnvironment(HRESULT result, ICoreWebView2Environment *environment)
{
    trace(QStringLiteral("environment callback=%1").arg(result));
    if (FAILED(result) || !environment || !m_host) {
        qWarning() << "Live code scene: WebView2 environment failed" << Qt::hex << result;
        m_failed = true;
        return;
    }
    m_environment = environment;
    Microsoft::WRL::ComPtr<ICoreWebView2Environment3> env3;
    result = environment->QueryInterface(IID_ICoreWebView2Environment3,
        reinterpret_cast<void **>(env3.GetAddressOf()));
    if (FAILED(result)) {
        m_failed = true;
        return;
    }
    auto done = new ControllerDone(this);
    result = env3->CreateCoreWebView2CompositionController(m_host, done);
    done->Release();
    if (FAILED(result)) {
        qWarning() << "Live code scene: WebView2 composition failed" << Qt::hex << result;
        m_failed = true;
    }
}

void LiveCodeOverlay::onController(HRESULT result, ICoreWebView2CompositionController *created)
{
    trace(QStringLiteral("controller callback=%1").arg(result));
    if (FAILED(result) || !created || !m_host) {
        qWarning() << "Live code scene: WebView2 controller failed" << Qt::hex << result;
        m_failed = true;
        return;
    }
    m_controller = created;
    result = m_controller->put_RootVisualTarget(m_visual.Get());
    if (SUCCEEDED(result))
        result = m_controller->QueryInterface(IID_ICoreWebView2Controller,
            reinterpret_cast<void **>(m_baseController.GetAddressOf()));
    Microsoft::WRL::ComPtr<ICoreWebView2Controller2> controller2;
    if (SUCCEEDED(result))
        result = m_baseController->QueryInterface(IID_ICoreWebView2Controller2,
            reinterpret_cast<void **>(controller2.GetAddressOf()));
    if (SUCCEEDED(result)) {
        const COREWEBVIEW2_COLOR transparent{0, 0, 0, 0};
        result = controller2->put_DefaultBackgroundColor(transparent);
    }
    if (SUCCEEDED(result))
        result = m_baseController->get_CoreWebView2(m_webview.GetAddressOf());
    if (FAILED(result)) {
        qWarning() << "Live code scene: transparent WebView2 setup failed" << Qt::hex << result;
        m_failed = true;
        return;
    }
    // Scene code is local and deterministic. Permit only files generated in
    // this revision's page folder; deny network and other local-file reads.
    auto resourceRequested = new ResourceRequested(this);
    EventRegistrationToken resourceToken;
    result = m_webview->AddWebResourceRequestedFilter(L"*", COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL);
    if (SUCCEEDED(result))
        result = m_webview->add_WebResourceRequested(resourceRequested, &resourceToken);
    resourceRequested->Release();
    if (FAILED(result)) {
        qWarning() << "Live code scene: could not isolate local page resources" << Qt::hex << result;
        m_failed = true;
        return;
    }
    m_lastBounds = QRect();
    updateBounds();
    m_composition->Commit();
    m_webview->AddScriptToExecuteOnDocumentCreated(
        L"window.chrome.webview.addEventListener('message', e => {"
        L"const d=e.data; if(d && Number.isFinite(d.time)) "
        L"window.dispatchEvent(new CustomEvent('hf-seek',{detail:{time:d.time,frame:d.frame}}));"
        L"if(d && d.markup) window.dispatchEvent(new CustomEvent('hf-markup',{detail:d.markup}));});"
        L"const letiteditFit=()=>{const r=document.getElementById('root');if(!r)return;"
        L"document.documentElement.style.overflow='hidden';"
        L"document.body.style.overflow='hidden';r.style.transformOrigin='0 0';"
        L"r.style.transform='scale('+Math.max(innerWidth/Number(r.dataset.width),"
        L"innerHeight/Number(r.dataset.height))+')';};"
        L"window.addEventListener('DOMContentLoaded',letiteditFit);"
        L"window.addEventListener('resize',letiteditFit);", nullptr);
    if (m_review) {
        m_webview->AddScriptToExecuteOnDocumentCreated(LR"JS(
window.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('root'); if (!root) return;
  const canvas = document.createElement('canvas');
  canvas.id = 'letitedit-review-marks';
  canvas.width = Number(root.dataset.width); canvas.height = Number(root.dataset.height);
  canvas.style.cssText = 'position:absolute;inset:0;z-index:2147483647;pointer-events:none';
  root.appendChild(canvas);
  window.addEventListener('hf-markup', e => {
    const g = canvas.getContext('2d'); g.clearRect(0, 0, canvas.width, canvas.height);
    const w = canvas.width, h = canvas.height;
    for (const s of e.detail) {
      if (!s.points || !s.points.length) continue;
      const p = s.points.map(x => [x[0]*w, x[1]*h]);
      g.lineWidth = Math.max(2.5, h*.007); g.lineJoin = 'round'; g.lineCap = 'round';
      g.strokeStyle = s.color; g.fillStyle = s.color; g.beginPath();
      if (s.tool === 2) { const a=p[0], b=p[p.length-1]; g.ellipse((a[0]+b[0])/2,(a[1]+b[1])/2,
          Math.abs(a[0]-b[0])/2,Math.abs(a[1]-b[1])/2,0,0,Math.PI*2); }
      else if (s.tool === 3) { const a=p[0], b=p[p.length-1];
          g.rect(Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.abs(a[0]-b[0]),Math.abs(a[1]-b[1])); }
      else { g.moveTo(...p[0]); for (const q of p.slice(1)) g.lineTo(...q); }
      g.stroke();
      if (s.tool === 1 && p.length > 1) { const a=p[0], b=p[p.length-1];
        const angle=Math.atan2(b[1]-a[1],b[0]-a[0]), size=Math.max(14,h*.022);
        g.beginPath(); g.moveTo(...b); g.lineTo(b[0]-size*Math.cos(angle-.55),b[1]-size*Math.sin(angle-.55));
        g.moveTo(...b); g.lineTo(b[0]-size*Math.cos(angle+.55),b[1]-size*Math.sin(angle+.55)); g.stroke(); }
      if (s.number) { const b=p[p.length-1]; g.font=`bold ${Math.max(14,h*.024)}px sans-serif`;
        g.fillText(String(s.number),b[0]+10,b[1]-10); }
    }
  });
});
)JS", nullptr);
    }
    auto navigationDone = new NavigationDone(this);
    EventRegistrationToken navigationToken;
    m_webview->add_NavigationCompleted(navigationDone, &navigationToken);
    navigationDone->Release();
    const QString url = QUrl::fromLocalFile(m_page).toString(QUrl::FullyEncoded);
    result = m_webview->Navigate(reinterpret_cast<const wchar_t *>(url.utf16()));
    if (FAILED(result)) {
        qWarning() << "Live code scene: could not open page" << m_page << Qt::hex << result;
        m_failed = true;
        return;
    }
    m_baseController->put_IsVisible(m_active && !sceneHeld());
    trace(QStringLiteral("navigated page=%1 bounds=%2x%3")
        .arg(m_page).arg(m_pictureRect.width()).arg(m_pictureRect.height()));
    qWarning() << "Live code scene controller ready" << m_page;
    sendFrame();
    sendMarkup();
}

void LiveCodeOverlay::onNavigation(ICoreWebView2NavigationCompletedEventArgs *args)
{
    BOOL success = FALSE;
    COREWEBVIEW2_WEB_ERROR_STATUS status = COREWEBVIEW2_WEB_ERROR_STATUS_UNKNOWN;
    args->get_IsSuccess(&success);
    args->get_WebErrorStatus(&status);
    trace(QStringLiteral("navigation success=%1 status=%2")
        .arg(success).arg(int(status)));
    auto done = new ScriptDone;
    m_webview->ExecuteScript(
        L"({title:document.title,root:!!document.getElementById('root'),"
        L"canvases:document.querySelectorAll('canvas').length,width:innerWidth,height:innerHeight})", done);
    done->Release();
    sendFrame();
    sendMarkup();
    const QString capturePath = qEnvironmentVariable("LETITEDIT_LIVE_SCENE_CAPTURE");
    if (!capturePath.isEmpty()) {
        QTimer::singleShot(500, this, [this, capturePath]() {
            if (!m_webview)
                return;
            Microsoft::WRL::ComPtr<IStream> stream;
            if (FAILED(CreateStreamOnHGlobal(nullptr, TRUE, stream.GetAddressOf())))
                return;
            auto captureDone = new CaptureDone(stream.Get(), capturePath);
            m_webview->CapturePreview(COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT_PNG,
                                      stream.Get(), captureDone);
            captureDone->Release();
        });
    }
}

void LiveCodeOverlay::onResourceRequested(ICoreWebView2WebResourceRequestedEventArgs *args)
{
    Microsoft::WRL::ComPtr<ICoreWebView2WebResourceRequest> request;
    LPWSTR rawUri = nullptr;
    if (FAILED(args->get_Request(request.GetAddressOf())) || !request
        || FAILED(request->get_Uri(&rawUri)))
        return;
    const QUrl url(QString::fromWCharArray(rawUri));
    CoTaskMemFree(rawUri);
    const QString local = QFileInfo(url.toLocalFile()).canonicalFilePath();
    const QString folder = m_pageInfo.dir().canonicalPath();
    if (url.scheme() == QLatin1String("file") && !local.isEmpty() && !folder.isEmpty()
        && local.startsWith(folder + QLatin1Char('/'), Qt::CaseInsensitive))
        return;
    Microsoft::WRL::ComPtr<ICoreWebView2WebResourceResponse> denied;
    if (m_environment && SUCCEEDED(m_environment->CreateWebResourceResponse(
            nullptr, 403, L"Forbidden", L"", denied.GetAddressOf())))
        args->put_Response(denied.Get());
    trace(QStringLiteral("blocked scene resource=%1").arg(url.toString()));
}

void LiveCodeOverlay::setPictureRect(const QRectF &rect)
{
    m_pictureRect = rect;
    updateBounds();
}

// The player's own native window must sit where the player widget is. With the scene layer attached to
// it (and its ancestors kept non-native), Qt can leave it at the window's top-left corner with the right
// size, so the player and the scene both draw over the header and the left bar. Put it back, and keep it
// there when panels open or the window moves (the 50 ms timer and every bounds update call this).
void LiveCodeOverlay::alignHost()
{
    if (!m_host || !m_video || !m_video->isVisible())
        return;
    QWidget *parent = m_video->nativeParentWidget();
    HWND parentWindow = GetParent(m_host);
    if (!parent || !parentWindow)
        return;
    const qreal scale = m_video->devicePixelRatioF();
    const QPoint at = m_video->mapTo(parent, QPoint(0, 0));
    const int x = qRound(at.x() * scale), y = qRound(at.y() * scale);
    const int w = qRound(m_video->width() * scale), h = qRound(m_video->height() * scale);
    RECT now;
    if (!GetWindowRect(m_host, &now))
        return;
    POINT corner{now.left, now.top};
    ScreenToClient(parentWindow, &corner);
    const int dx = corner.x - x, dy = corner.y - y;
    const int dw = (now.right - now.left) - w, dh = (now.bottom - now.top) - h;
    if (qAbs(dx) <= 1 && qAbs(dy) <= 1 && qAbs(dw) <= 1 && qAbs(dh) <= 1)
        return;
    SetWindowPos(m_host, nullptr, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER);
    trace(QStringLiteral("align host from %1,%2 %3x%4 to %5,%6 %7x%8")
          .arg(corner.x).arg(corner.y).arg(now.right - now.left).arg(now.bottom - now.top)
          .arg(x).arg(y).arg(w).arg(h));
}

void LiveCodeOverlay::updateBounds()
{
    if (!m_host || !m_video)
        return;
    alignHost();
    const qreal scale = m_video->devicePixelRatioF();
    // Round outward: a rounded-down edge leaves a one-pixel line of the footage beside the scene.
    const int left = qFloor(m_pictureRect.left() * scale), top = qFloor(m_pictureRect.top() * scale);
    const QRect bounds(left, top, qMax(1, qCeil((m_pictureRect.left() + m_pictureRect.width()) * scale) - left),
        qMax(1, qCeil((m_pictureRect.top() + m_pictureRect.height()) * scale) - top));
    if (bounds == m_lastBounds)
        return;
    m_lastBounds = bounds;
    if (m_fallbackLabel)
        m_fallbackLabel->setGeometry(m_pictureRect.toAlignedRect());
    if (m_visual) {
        m_visual->SetOffsetX(float(bounds.x()));
        m_visual->SetOffsetY(float(bounds.y()));
        m_composition->Commit();
    }
    if (m_baseController) {
        RECT childBounds{0, 0, bounds.width(), bounds.height()};
        m_baseController->put_Bounds(childBounds);
    }
    trace(QStringLiteral("bounds=%1,%2 %3x%4 dpi=%5")
          .arg(bounds.x()).arg(bounds.y()).arg(bounds.width()).arg(bounds.height()).arg(scale));
}

void LiveCodeOverlay::onFrame(int timelineFrame, double fps)
{
    if (!m_enabled)
        return;
    m_lastFrame = timelineFrame;
    m_fps = fps > 0 ? fps : 30.0;
    syncTimeline(timelineFrame);
    m_active = timelineFrame >= m_startFrame && timelineFrame < m_endFrame;
    if (!m_loggedFrame) {
        qWarning() << "Live code scene first frame" << timelineFrame << fps << m_active;
        m_loggedFrame = true;
        trace(QStringLiteral("first frame=%1 fps=%2 active=%3")
            .arg(timelineFrame).arg(fps).arg(m_active));
    }
    if (!m_active) {
        if (m_baseController)
            m_baseController->put_IsVisible(FALSE);
        if (m_fallbackLabel)
            m_fallbackLabel->hide();
        return;
    }
    if (!m_started && !m_page.isEmpty())
        initialize();
    // Nothing is drawn over the video until the masks for what sits above this scene are there.
    const bool held = sceneHeld();
    showHold(held);
    if (held) {
        if (m_baseController)
            m_baseController->put_IsVisible(FALSE);
        if (m_fallbackLabel)
            m_fallbackLabel->hide();
        return;
    }
    if (m_failed) {
        showFallback();
        return;
    }
    if (m_webview) {
        updateBounds();
        m_baseController->put_IsVisible(TRUE);
        sendFrame();
    }
}

// True while this scene must stay hidden: its page has no masks that fit where the scene is now, so it would cover
// the person and captions drawn by the video under it. A probe page (the environment variables) has no such file.
bool LiveCodeOverlay::sceneHeld()
{
    if (m_page.isEmpty() || !qEnvironmentVariable("LETITEDIT_LIVE_SCENE_PAGE").isEmpty())
        return false;
    const QFileInfo info(QFileInfo(m_page).dir().absolutePath() + QStringLiteral("/../upper-mask.json"));
    if (!info.exists()) {
        m_maskInfoPath.clear();
        return true;
    }
    if (info.absoluteFilePath() != m_maskInfoPath || info.lastModified() != m_maskInfoTime) {
        QFile file(info.absoluteFilePath());
        if (!file.open(QIODevice::ReadOnly))
            return true;
        const QJsonObject values = QJsonDocument::fromJson(file.readAll()).object();
        m_maskStart = values.value(QStringLiteral("start")).toInt(-1);
        m_maskFrames = values.value(QStringLiteral("frames")).toInt(-1);
        m_maskInfoPath = info.absoluteFilePath();
        m_maskInfoTime = info.lastModified();
    }
    if (m_maskStart != m_startFrame || m_maskFrames < 0)
        return true; // the scene moved since these were drawn
    return m_maskDrawing && m_maskNoOldSet;
}

// Say what is happening, where the person is looking, while a scene in view is hidden or its masks are being redrawn.
void LiveCodeOverlay::showHold(bool held)
{
    if (held != m_held) {
        trace(QStringLiteral("scene %1 at frame %2 drawn %3/%4")
                  .arg(held ? QStringLiteral("held") : QStringLiteral("shown"))
                  .arg(m_lastFrame).arg(m_maskDone).arg(m_maskTotal));
        m_holdSaid = false;
    }
    m_held = held;
    if (m_review || m_holdSaid || (!held && !m_maskDrawing))
        return;
    m_holdSaid = true;
    const QString amount = m_maskTotal > 0 ? QObject::tr(", %1% done").arg(100 * m_maskDone / m_maskTotal) : QString();
    if (held)
        MAIN.showStatusMessage(QObject::tr("Getting this scene ready for the player%1. It stays hidden here until then "
                                           "so it can't cover anything; the export has it.").arg(amount), 15);
    else
        MAIN.showStatusMessage(QObject::tr("Updating this scene for the player%1. Until it finishes, what's in front of "
                                           "it can look slightly off here; the export isn't affected.").arg(amount), 15);
}

void LiveCodeOverlay::showFallback()
{
    if (m_page.isEmpty() || !m_video)
        return;
    if (!m_fallbackLabel) {
        m_fallbackLabel = new QLabel(m_video);
        m_fallbackLabel->setAttribute(Qt::WA_TransparentForMouseEvents);
        m_fallbackLabel->setStyleSheet(QStringLiteral("background: transparent"));
        m_fallbackLabel->setScaledContents(true);
    }
    m_fallbackLabel->setGeometry(m_pictureRect.toAlignedRect());
    if (m_fallbackPage != m_page) {
        m_fallbackPage = m_page;
        m_fallbackFrames.clear();
        m_fallbackIndex = -1;
        m_fallbackLabel->hide();
    }
    if (m_fallbackFrames.isEmpty()) {
        startFallback();
        return;
    }
    const int index = qBound(0, qRound((m_lastFrame - m_startFrame + m_frameOffset)
                                     / m_fps * m_fallbackFps), m_fallbackFrames.size() - 1);
    if (index != m_fallbackIndex) {
        m_fallbackIndex = index;
        QPixmap picture(m_fallbackFrames[index]);
        if (m_review && !picture.isNull() && !m_reviewMarkup.isEmpty()) {
            const QJsonArray strokes = QJsonDocument::fromJson(m_reviewMarkup)
                                           .object().value(QStringLiteral("markup")).toArray();
            QPainter painter(&picture);
            painter.setRenderHint(QPainter::Antialiasing);
            for (const QJsonValue &value : strokes) {
                const QJsonObject stroke = value.toObject();
                const QJsonArray raw = stroke.value(QStringLiteral("points")).toArray();
                QPolygonF points;
                for (const QJsonValue &point : raw) {
                    const QJsonArray xy = point.toArray();
                    if (xy.size() >= 2)
                        points << QPointF(xy[0].toDouble() * picture.width(),
                                          xy[1].toDouble() * picture.height());
                }
                if (points.isEmpty())
                    continue;
                const QColor color(stroke.value(QStringLiteral("color")).toString());
                QPen pen(color, qMax(2.5, picture.height() * .007), Qt::SolidLine,
                         Qt::RoundCap, Qt::RoundJoin);
                painter.setPen(pen);
                const int tool = stroke.value(QStringLiteral("tool")).toInt();
                if (tool == 2 && points.size() > 1)
                    painter.drawEllipse(QRectF(points.first(), points.last()).normalized());
                else if (tool == 3 && points.size() > 1)
                    painter.drawRect(QRectF(points.first(), points.last()).normalized());
                else
                    painter.drawPolyline(points);
                const int number = stroke.value(QStringLiteral("number")).toInt();
                if (number > 0)
                    painter.drawText(points.last() + QPointF(10, -10), QString::number(number));
            }
        }
        m_fallbackLabel->setPixmap(picture);
    }
    m_fallbackLabel->raise();
    m_fallbackLabel->show();
}

void LiveCodeOverlay::startFallback()
{
    if (m_fallbackProcess || m_page.isEmpty())
        return;
    const QString python = aiChatSettings().value(QStringLiteral("python")).toString();
    const QString helper = aiRootPath(QStringLiteral("bridge/code_scenes.py"));
    if (!QFileInfo::exists(python) || !QFileInfo::exists(helper))
        return;
    auto process = new QProcess(this);
    m_fallbackProcess = process;
    const QString requestedPage = m_page;
    process->setProcessChannelMode(QProcess::MergedChannels);
    connect(process, &QProcess::finished, this, [this, process, requestedPage](int exitCode) {
        const QByteArray output = process->readAll();
        m_fallbackProcess = nullptr;
        process->deleteLater();
        if (exitCode != 0) {
            qWarning() << "Code scene fallback preview failed" << output.right(500);
            return;
        }
        const QJsonObject result = QJsonDocument::fromJson(output.trimmed()).object();
        const QDir folder(result.value(QStringLiteral("folder")).toString());
        if (requestedPage != m_page || !folder.exists()) {
            if (m_active)
                startFallback();
            return;
        }
        for (const QString &file : folder.entryList({QStringLiteral("frame-*.png")}, QDir::Files, QDir::Name))
            m_fallbackFrames << folder.filePath(file);
        m_fallbackFps = result.value(QStringLiteral("fps")).toInt(12);
        m_fallbackIndex = -1;
        trace(QStringLiteral("fallback frames=%1 page=%2")
              .arg(m_fallbackFrames.size()).arg(requestedPage));
        if (!m_fallbackFrames.isEmpty())
            showFallback();
    });
    process->start(python, {helper, QStringLiteral("--preview"),
                            QFileInfo(m_page).dir().absolutePath() + QStringLiteral("/..")});
}

void LiveCodeOverlay::sendFrame()
{
    if (!m_webview || !m_active)
        return;
    const double time = qMax(0.0, (m_lastFrame - m_startFrame + m_frameOffset) / m_fps);
    // frame: from the scene's first frame on the timeline, which the masks count from; time also holds a trimmed start.
    const QString message = QStringLiteral("{\"time\":%1,\"frame\":%2}").arg(time, 0, 'f', 6)
                                .arg(qMax(0, m_lastFrame - m_startFrame));
    m_webview->PostWebMessageAsJson(reinterpret_cast<const wchar_t *>(message.utf16()));
}

void LiveCodeOverlay::setReviewMarkup(const QJsonArray &strokes)
{
    if (!m_review)
        return;
    m_reviewMarkup = QJsonDocument(QJsonObject{{QStringLiteral("markup"), strokes}}).toJson(QJsonDocument::Compact);
    if (m_failed) {
        m_fallbackIndex = -1;
        if (m_active)
            showFallback();
    }
    sendMarkup();
}

QImage LiveCodeOverlay::captureReviewScene()
{
    if (!m_review || !m_active)
        return {};
    if (m_failed) {
        if (m_fallbackFrames.isEmpty())
            return {};
        const int index = qBound(0, qRound((m_lastFrame - m_startFrame + m_frameOffset)
                                          / m_fps * m_fallbackFps), m_fallbackFrames.size() - 1);
        return QImage(m_fallbackFrames[index]);
    }
    if (!m_webview)
        return {};
    // The saved note draws its strokes itself, so capture only the scene art.
    m_webview->ExecuteScript(L"{const e=document.getElementById('letitedit-review-marks');"
                             L"if(e)e.style.visibility='hidden';}", nullptr);
    Microsoft::WRL::ComPtr<IStream> stream;
    if (FAILED(CreateStreamOnHGlobal(nullptr, TRUE, stream.GetAddressOf())))
        return {};
    QEventLoop loop;
    QImage image;
    auto done = new CaptureReviewDone(stream.Get(), &loop, &image);
    const HRESULT result = m_webview->CapturePreview(COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT_PNG,
                                                      stream.Get(), done);
    done->Release();
    if (SUCCEEDED(result)) {
        QTimer::singleShot(1000, &loop, &QEventLoop::quit);
        loop.exec();
    }
    m_webview->ExecuteScript(L"{const e=document.getElementById('letitedit-review-marks');"
                             L"if(e)e.style.visibility='visible';}", nullptr);
    return image;
}

void LiveCodeOverlay::sendMarkup()
{
    if (m_review && m_webview && m_active && !m_reviewMarkup.isEmpty()) {
        const QString message = QString::fromUtf8(m_reviewMarkup);
        m_webview->PostWebMessageAsJson(reinterpret_cast<const wchar_t *>(message.utf16()));
    }
}

void LiveCodeOverlay::syncTimeline(int timelineFrame)
{
    if (timelineFrame < 0 || !MAIN.multitrack() || MAIN.fileName().isEmpty())
        return;
    Mlt::Tractor tractor(*MAIN.multitrack());
    const QFileInfo project(MAIN.fileName());
    const QDir scenes(project.dir().filePath(project.completeBaseName() + QStringLiteral(".letitedit/scenes")));
    static const QRegularExpression safeId(QStringLiteral("^[a-z0-9][a-z0-9_-]{0,63}$"));
    static const QRegularExpression safeHash(QStringLiteral("^[0-9a-f]{14}$"));
    QString selectedPage;
    int selectedStart = 0, selectedEnd = 0, selectedOffset = 0;
    int sceneTrack = -1, topBlockTrack = -1; // a block (adjustment layer) on a track above the scene changes it
    for (int track = 0; track < tractor.count(); ++track) {
        QScopedPointer<Mlt::Producer> trackProducer(tractor.track(track));
        if (!trackProducer || !trackProducer->is_valid())
            continue;
        Mlt::Playlist playlist(*trackProducer);
        // MLT knows the active entry at this frame. Scanning a long playlist
        // for every displayed frame made scene lookup grow with video length.
        const int clip = playlist.get_clip_index_at(timelineFrame);
        if (clip >= 0 && clip < playlist.count() && !playlist.is_blank(clip)) {
            QScopedPointer<Mlt::ClipInfo> info(playlist.clip_info(clip));
            if (!info || !info->producer || timelineFrame < info->start
                || timelineFrame >= info->start + info->frame_count)
                continue;
            if (info->producer->get_int("meta.fx_cut"))
                topBlockTrack = track;
            const char *raw = info->producer->get("letitedit_ai:code_scene");
            if (!raw || !*raw)
                continue;
            const QJsonObject marker = QJsonDocument::fromJson(raw).object();
            const QString id = marker.value(QStringLiteral("id")).toString();
            const QString revision = marker.value(QStringLiteral("revision")).toString();
            if (!safeId.match(id).hasMatch() || !safeHash.match(revision).hasMatch())
                continue;
            const QString page = scenes.filePath(id + QStringLiteral("/revisions/") + revision
                                                 + QStringLiteral("/page/index.html"));
            if (!QFileInfo::exists(page))
                continue;
            selectedPage = page;
            sceneTrack = track;
            selectedStart = info->start;
            selectedEnd = info->start + info->frame_count;
            selectedOffset = info->frame_in;
        }
    }
    // The export draws a block over a scene; this live layer is a web page and does not. Say so where the
    // person is looking, once each time the playhead comes onto such a stretch.
    const bool blockOverScene = !m_review && !selectedPage.isEmpty() && topBlockTrack > sceneTrack;
    if (blockOverScene && !m_blockNoted)
        MAIN.showStatusMessage(QObject::tr("An adjustment layer is over this scene. The exported video shows its "
                                           "effect on the scene; this preview doesn't."), 10);
    m_blockNoted = blockOverScene;
    if (selectedPage.isEmpty()) {
        if (qEnvironmentVariable("LETITEDIT_LIVE_SCENE_PAGE").isEmpty()) {
            m_startFrame = m_endFrame = 0;
            if (m_baseController)
                m_baseController->put_IsVisible(FALSE);
        }
        return;
    }
    m_startFrame = selectedStart;
    m_endFrame = selectedEnd;
    m_frameOffset = selectedOffset;
    if (selectedPage != m_page) {
        m_page = selectedPage;
        m_pageInfo.setFile(m_page);
        if (m_webview) {
            const QString url = QUrl::fromLocalFile(m_page).toString(QUrl::FullyEncoded);
            m_webview->Navigate(reinterpret_cast<const wchar_t *>(url.utf16()));
        }
        trace(QStringLiteral("scene page=%1 range=%2..%3 offset=%4")
              .arg(m_page).arg(m_startFrame).arg(m_endFrame).arg(m_frameOffset));
        // Edits made while no window showed this project left its masks stale on purpose (nobody was
        // playing). Now a scene is up: check them once per opened project (quick when they are current).
        if (m_refreshedProject != MAIN.fileName()) {
            m_refreshedProject = MAIN.fileName();
            refreshAfterTimelineEdit();
        }
    }
}

void LiveCodeOverlay::checkPage()
{
    alignHost();
    startRefreshForOpenProject();
    // The masks arrive while the player is paused too: bring the scene up, or take it down, without a new frame.
    if (m_active && !m_page.isEmpty() && sceneHeld() != m_held)
        onFrame(m_lastFrame, m_fps);
    if (!m_review && !m_refreshConnected && MAIN.undoStack()) {
        m_refreshConnected = true;
        connect(MAIN.undoStack(), &QUndoStack::indexChanged, this,
                [this](int) { refreshAfterTimelineEdit(); });
    }
    if (m_failed) {
        const QDateTime previous = m_pageInfo.lastModified();
        m_pageInfo.refresh();
        if (m_pageInfo.lastModified() != previous) {
            m_fallbackFrames.clear();
            m_fallbackIndex = -1;
            if (m_fallbackLabel)
                m_fallbackLabel->hide();
            if (m_active)
                startFallback();
        }
        return;
    }
    if (!m_webview)
        return;
    const QDateTime previous = m_pageInfo.lastModified();
    m_pageInfo.refresh();
    if (m_pageInfo.lastModified() != previous) {
        m_webview->Reload();
        QTimer::singleShot(100, this, [this]() { sendFrame(); });
    }
}

// A window that opens a project with scenes starts its masks straight away, not when the playhead first reaches a
// scene: drawing takes minutes and goes on in the background, in short turns of the PC lock.
void LiveCodeOverlay::startRefreshForOpenProject()
{
    if (m_review || MAIN.fileName() == m_openedProject)
        return;
    m_openedProject = MAIN.fileName();
    m_refreshRetries = 0;
    if (m_openedProject.isEmpty())
        return;
    const QFileInfo project(m_openedProject);
    if (QDir(project.dir().filePath(project.completeBaseName() + QStringLiteral(".letitedit/scenes"))).exists()) {
        m_refreshedProject = m_openedProject; // no second check when a scene first comes up
        QTimer::singleShot(1500, this, [this]() { refreshAfterTimelineEdit(); });
    }
}

void LiveCodeOverlay::refreshAfterTimelineEdit()
{
    if (!m_enabled || m_review || MAIN.fileName().isEmpty())
        return;
    if (m_page.isEmpty()) {
        const QFileInfo project(MAIN.fileName());
        if (!QDir(project.dir().filePath(project.completeBaseName() + QStringLiteral(".letitedit/scenes"))).exists())
            return;
    }
    m_refreshDirty = true;
    m_refreshDebounce.start();
}

void LiveCodeOverlay::startRefresh()
{
    if (!m_refreshDirty || m_refreshProcess || MAIN.fileName().isEmpty())
        return;
    const QString python = aiChatSettings().value(QStringLiteral("python")).toString();
    const QString helper = aiRootPath(QStringLiteral("bridge/code_scenes.py"));
    if (!QFileInfo::exists(python) || !QFileInfo::exists(helper))
        return;
    m_refreshDirty = false;
    auto process = new QProcess(this);
    m_refreshProcess = process;
    process->setProcessChannelMode(QProcess::MergedChannels);
    m_maskDone = m_maskTotal = 0;
    connect(process, &QProcess::readyRead, this, [this]() { readRefreshProgress(); });
    connect(process, &QProcess::finished, this, [this, process](int exitCode) {
        readRefreshProgress();
        trace(QStringLiteral("upper alpha refresh exit=%1 output=%2")
              .arg(exitCode).arg(QString::fromUtf8(m_refreshLast + process->readAll()).right(300)));
        m_refreshProcess = nullptr;
        process->deleteLater();
        m_maskDrawing = m_maskNoOldSet = false;
        m_maskInfoPath.clear(); // read the finished set's facts again
        if (m_refreshDirty) {
            m_refreshDebounce.start();
        } else if (exitCode != 0 && m_refreshRetries < 5) {
            // Another window or an AI edit was drawing this scene's masks, or a run failed: look again shortly.
            // The scene stays hidden if no set fits, so nothing is covered meanwhile.
            ++m_refreshRetries;
            QTimer::singleShot(30000, this, [this]() { refreshAfterTimelineEdit(); });
        } else if (exitCode != 0 && m_active && sceneHeld()) {
            MAIN.showStatusMessage(QObject::tr("This scene can't be shown in the player right now, so it stays hidden "
                                               "here. The export isn't affected."), 30);
        }
    });
    process->start(python, {helper, QStringLiteral("--refresh"), MAIN.fileName(), QStringLiteral("--window-pid"),
                            QString::number(QCoreApplication::applicationPid())});
}

// The helper says {"masks": "drawing", "done": n, "of": m, "old_set": bool} before and during a long draw.
void LiveCodeOverlay::readRefreshProgress()
{
    if (!m_refreshProcess)
        return;
    while (m_refreshProcess->canReadLine()) {
        const QByteArray line = m_refreshProcess->readLine().trimmed();
        if (!line.startsWith("{\"masks\"")) {
            m_refreshLast = line;   // the last thing it said, for the trace when it fails
            continue;
        }
        const QJsonObject progress = QJsonDocument::fromJson(line).object();
        m_maskDrawing = true;
        m_maskNoOldSet = !progress.value(QStringLiteral("old_set")).toBool();
        m_maskDone = progress.value(QStringLiteral("done")).toInt();
        m_maskTotal = progress.value(QStringLiteral("of")).toInt();
        m_holdSaid = false; // the next frame or timer tick says the new amount
        if (m_active)
            onFrame(m_lastFrame, m_fps);
    }
}

#endif
