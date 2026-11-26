/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * The AI dock's interactive Windows terminal: ConPTY, libvterm and a Qt canvas.
 */
#ifndef AITERMINAL_H
#define AITERMINAL_H

#include <QWidget>
#include <functional>
#include <memory>

class AiTerminal : public QWidget
{
public:
    explicit AiTerminal(QWidget *parent = nullptr);
    ~AiTerminal() override;
    bool start(const QString &program, const QStringList &arguments, const QString &workDir, QString *error,
               const QStringList &extraEnvironment = QStringList());
    void stop();
    bool running() const;
    void send(const QByteArray &bytes);
    // T99: called as the person presses Enter on something they typed. False holds it back; extra goes on the end of the message.
    void setSubmitHook(std::function<bool(QString *extra)> hook);
    void paste(const QString &text);
    void submit(const QString &text);
    void interrupt();
    QString visibleText() const;
    qint64 receivedBytes() const;
    qint64 sentBytes() const;
    std::function<void(int)> exited;

protected:
    void paintEvent(QPaintEvent *) override;
    void resizeEvent(QResizeEvent *) override;
    bool event(QEvent *event) override;
    void keyPressEvent(QKeyEvent *) override;
    void wheelEvent(QWheelEvent *) override;
    void mousePressEvent(QMouseEvent *) override;
    void mouseMoveEvent(QMouseEvent *) override;
    void mouseReleaseEvent(QMouseEvent *) override;
    void contextMenuEvent(QContextMenuEvent *) override;

private:
    struct Private;
    void receive(const QByteArray &bytes);
    void dimensions();
    void output();
    QString selectionText() const;
    std::unique_ptr<Private> d;
};

#endif
