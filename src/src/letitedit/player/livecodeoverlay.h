#pragma once

#include <QtGlobal>

#ifdef Q_OS_WIN

#include <QFileInfo>
#include <QImage>
#include <QLabel>
#include <QJsonArray>
#include <QObject>
#include <QPointer>
#include <QProcess>
#include <QRectF>
#include <QRect>
#include <QStringList>
#include <QTimer>
#include <QWidget>
#include <d3d11.h>
#include <dcomp.h>
#include <wrl.h>
#include "../../../third_party/webview2/include/WebView2.h"

// Player surface for saved code-scene timeline items. Set
// LETITEDIT_LIVE_SCENES=0 only for a diagnostic opt-out.
// Scene items and their immutable revision hashes are read from the live MLT
// timeline, so editor Undo/Redo and timeline moves drive the displayed page.
class LiveCodeOverlay : public QObject
{
public:
    explicit LiveCodeOverlay(QWidget *video, bool review = false);
    ~LiveCodeOverlay() override;

    void setPictureRect(const QRectF &rect);
    void onFrame(int timelineFrame, double fps);
    void setReviewMarkup(const QJsonArray &strokes);
    QImage captureReviewScene();
    void onEnvironment(HRESULT result, ICoreWebView2Environment *environment);
    void onController(HRESULT result, ICoreWebView2CompositionController *created);
    void onNavigation(ICoreWebView2NavigationCompletedEventArgs *args);
    void onResourceRequested(ICoreWebView2WebResourceRequestedEventArgs *args);

private:
    bool initialize();
    void updateBounds();
    void alignHost();
    void sendFrame();
    void sendMarkup();
    void checkPage();
    void syncTimeline(int timelineFrame);
    void refreshAfterTimelineEdit();
    void startRefresh();
    void showFallback();
    void startFallback();
    void startRefreshForOpenProject();
    bool sceneHeld();
    void showHold(bool held);
    void readRefreshProgress();
    static LRESULT CALLBACK hostProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam);

    QPointer<QWidget> m_video;
    QString m_page;
    QFileInfo m_pageInfo;
    QTimer m_pageTimer;
    QTimer m_refreshDebounce;
    QPointer<QProcess> m_refreshProcess;
    QPointer<QProcess> m_fallbackProcess;
    QPointer<QLabel> m_fallbackLabel;
    QString m_fallbackPage;
    QStringList m_fallbackFrames;
    int m_fallbackFps = 12;
    int m_fallbackIndex = -1;
    QRectF m_pictureRect;
    QRect m_lastBounds;
    int m_startFrame = 0;
    int m_endFrame = 0;
    int m_lastFrame = 0;
    int m_frameOffset = 0;
    double m_fps = 30.0;
    bool m_enabled = false;
    bool m_review = false;
    QByteArray m_reviewMarkup;
    bool m_active = false;
    bool m_started = false;
    bool m_failed = false;
    bool m_loggedFrame = false;
    bool m_blockNoted = false;
    bool m_comInitialized = false;
    bool m_refreshConnected = false;
    QString m_refreshedProject; // the project whose scene masks were last checked when a scene came up
    // Masks for what sits above a scene. Without a set that fits, the page would cover the person and captions,
    // so the scene is held back (hidden) until one exists: the player then shows the video without the scene.
    QString m_openedProject;       // the project the masks were last started for when it opened
    QDateTime m_maskInfoTime;      // when <revision>/upper-mask.json was last changed, as last read
    QString m_maskInfoPath;
    int m_maskStart = -1;          // what it says
    int m_maskFrames = -1;
    bool m_maskDrawing = false;    // the helper is drawing a set
    bool m_maskNoOldSet = false;   // ... and no earlier set can stand in meanwhile
    int m_maskDone = 0;            // frames drawn so far of m_maskTotal
    int m_maskTotal = 0;
    int m_refreshRetries = 0;
    bool m_held = false;
    bool m_holdSaid = false;       // the status bar already says the current amount
    QByteArray m_refreshLast;
    bool m_refreshDirty = false;
    HWND m_host = nullptr;
    HMODULE m_loader = nullptr;
    Microsoft::WRL::ComPtr<ID3D11Device> m_d3d;
    Microsoft::WRL::ComPtr<IDCompositionDevice> m_composition;
    Microsoft::WRL::ComPtr<IDCompositionTarget> m_target;
    Microsoft::WRL::ComPtr<IDCompositionVisual> m_visual;
    Microsoft::WRL::ComPtr<ICoreWebView2CompositionController> m_controller;
    Microsoft::WRL::ComPtr<ICoreWebView2Controller> m_baseController;
    Microsoft::WRL::ComPtr<ICoreWebView2> m_webview;
    Microsoft::WRL::ComPtr<ICoreWebView2Environment> m_environment;
};

#endif
