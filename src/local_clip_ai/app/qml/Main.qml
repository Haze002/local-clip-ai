pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1240
    height: 800
    minimumWidth: 980
    minimumHeight: 660
    visible: true
    title: "Local Clip AI"
    color: "#0b0d12"
    Material.theme: Material.Dark
    Material.accent: Material.Blue
    Material.primary: "#182233"
    property int currentPage: 0
    property bool monitorVisible: false
    property var pages: ["Queue", "Results", "Profiles", "Monitor", "Diagnostics", "Settings"]

    function statusColor(status) {
        if (status === "pass" || status === "completed") return "#51d88a"
        if (status === "warn" || status === "paused" || status === "pause_pending")
            return "#f5bd58"
        if (status === "fail" || status === "failed" || status === "cancelled")
            return "#ff6b7a"
        if (status === "running") return "#67a7ff"
        return "#8792a5"
    }

    function reuseValue(index) {
        return ["none", "content", "analysis", "both"][index]
    }

    function metric(value, decimals, suffix) {
        if (value === undefined || value === null)
            return "Unavailable"
        return Number(value).toFixed(decimals) + suffix
    }

    onClosing: function(close) {
        if (trayController.available && !trayController.quitRequested) {
            close.accepted = false
            window.hide()
            trayController.notify(
                "Local Clip AI",
                queueController.running
                    ? "Analysis is still running in the system tray."
                    : "Local Clip AI is available from the system tray."
            )
        }
    }

    onVisibilityChanged: {
        if (visibility === Window.Minimized && trayController.available) {
            window.hide()
        }
    }

    Connections {
        target: trayController
        function onShowRequested() {
            window.show()
            window.raise()
            window.requestActivate()
        }
    }

    DropArea {
        anchors.fill: parent
        onDropped: function(drop) {
            if (drop.hasUrls) {
                queueController.queueSources(
                    drop.urls,
                    modeSelector.currentText.toLowerCase(),
                    window.reuseValue(reuseSelector.currentIndex)
                )
                window.currentPage = 0
            } else if (drop.hasText) {
                sourceField.text = drop.text
                window.currentPage = 0
            }
        }
    }

    Rectangle {
        id: sidebar
        width: 218
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        color: "#10141c"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 10

            Label {
                text: "LOCAL CLIP AI"
                color: "#f4f7fb"
                font.pixelSize: 19
                font.weight: Font.DemiBold
                Layout.bottomMargin: 24
            }

            Repeater {
                model: window.pages
                delegate: Rectangle {
                    required property string modelData
                    required property int index
                    Layout.fillWidth: true
                    implicitHeight: 42
                    radius: 10
                    color: window.currentPage === index ? "#232b3a" : "transparent"

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.leftMargin: 14
                        text: modelData
                        color: window.currentPage === index ? "#ffffff" : "#8792a5"
                        font.pixelSize: 14
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: window.currentPage = index
                    }
                }
            }

            Item { Layout.fillHeight: true }

            Button {
                Layout.fillWidth: true
                text: window.monitorVisible ? "Hide monitor" : "Show monitor"
                onClicked: window.monitorVisible = !window.monitorVisible
            }

            Label {
                text: "WINDOWS BETA BUILD"
                color: "#697589"
                font.pixelSize: 10
                font.letterSpacing: 1.2
            }
            Label {
                text: "Private and local by default"
                color: "#aab3c2"
                font.pixelSize: 11
            }
        }
    }

    Rectangle {
        id: noticeBanner
        visible: queueController.notice.length > 0
        anchors.top: parent.top
        anchors.left: sidebar.right
        anchors.right: parent.right
        height: visible ? 46 : 0
        color: queueController.noticeIsError ? "#3c222a" : "#183429"
        z: 3

        Label {
            anchors.centerIn: parent
            width: parent.width - 48
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: queueController.notice
            color: queueController.noticeIsError ? "#ff9aa6" : "#7de4a9"
            font.pixelSize: 12
        }
    }

    StackLayout {
        anchors.top: noticeBanner.visible ? noticeBanner.bottom : parent.top
        anchors.bottom: parent.bottom
        anchors.left: sidebar.right
        anchors.right: parent.right
        currentIndex: window.currentPage

        Item {
            id: queuePage

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 30
                spacing: 18

                ColumnLayout {
                    spacing: 4
                    Label {
                        text: "Analysis queue"
                        color: "#f4f7fb"
                        font.pixelSize: 27
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: "Paste a Twitch VOD, drop local recordings, or drop several files at once."
                        color: "#8e99ab"
                        font.pixelSize: 13
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 164
                    radius: 14
                    color: "#141a24"
                    border.width: 1
                    border.color: "#202939"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 12

                        TextField {
                            id: sourceField
                            Layout.fillWidth: true
                            placeholderText: "https://www.twitch.tv/videos/... or C:\\recordings\\vod.mkv"
                            color: "#f4f7fb"
                            placeholderTextColor: "#647086"
                            selectByMouse: true
                            onAccepted: addButton.clicked()
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            Label { text: "Analysis"; color: "#aab3c2" }
                            ComboBox {
                                id: modeSelector
                                model: ["Quick", "Balanced", "Deep"]
                                currentIndex: 1
                                Layout.preferredWidth: 140
                            }

                            Label {
                                text: "Reuse previous"
                                color: "#aab3c2"
                                Layout.leftMargin: 10
                            }
                            ComboBox {
                                id: reuseSelector
                                model: [
                                    "Nothing",
                                    "Content preference",
                                    "Analysis + exact mode",
                                    "Both"
                                ]
                                Layout.preferredWidth: 200
                            }

                            Item { Layout.fillWidth: true }

                            Button {
                                id: addButton
                                text: "Add to queue"
                                enabled: sourceField.text.trim().length > 0
                                onClicked: {
                                    queueController.queueSource(
                                        sourceField.text,
                                        modeSelector.currentText.toLowerCase(),
                                        window.reuseValue(reuseSelector.currentIndex)
                                    )
                                    sourceField.clear()
                                }
                            }
                        }

                        Label {
                            text: "Drop files anywhere in this window. Twitch links are verified in the background."
                            color: "#657188"
                            font.pixelSize: 11
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        text: "QUEUED VODS"
                        color: "#697589"
                        font.pixelSize: 11
                        font.letterSpacing: 1.4
                    }
                    Item { Layout.fillWidth: true }
                    Button {
                        text: queueController.running ? "Queue running..." : "Start queue"
                        enabled: !queueController.running
                        onClicked: queueController.startQueue()
                    }
                    Button {
                        text: "Refresh"
                        flat: true
                        onClicked: queueController.refresh()
                    }
                }

                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    Column {
                        width: parent.width
                        spacing: 10

                        Repeater {
                            model: jobsModel

                            delegate: Rectangle {
                                required property string jobId
                                required property string jobSource
                                required property string jobStatus
                                required property string jobMode
                                required property real jobProgress
                                required property string jobStage
                                required property string jobPauseReason
                                width: parent.width
                                height: 102
                                radius: 12
                                color: "#111720"
                                border.width: 1
                                border.color: "#1c2635"

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 16
                                    spacing: 14

                                    Rectangle {
                                        Layout.preferredWidth: 11
                                        Layout.preferredHeight: 11
                                        radius: 6
                                        color: window.statusColor(jobStatus)
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 5

                                        Label {
                                            Layout.fillWidth: true
                                            text: jobSource
                                            color: "#f4f7fb"
                                            font.pixelSize: 13
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideMiddle
                                        }
                                        Label {
                                            text: jobMode.toUpperCase() + "  /  " + jobStage
                                            color: "#8792a5"
                                            font.pixelSize: 11
                                        }
                                        ProgressBar {
                                            Layout.fillWidth: true
                                            from: 0
                                            to: 1
                                            value: jobProgress
                                        }
                                    }

                                    Label {
                                        text: jobStatus.replace("_", " ").toUpperCase()
                                        color: window.statusColor(jobStatus)
                                        font.pixelSize: 10
                                        font.weight: Font.Bold
                                    }

                                    Button {
                                        text: jobStatus === "paused" || jobStatus === "interrupted"
                                              || jobStatus === "failed" ? "Resume" : "Pause"
                                        enabled: ["completed", "cancelled"].indexOf(jobStatus) < 0
                                        onClicked: {
                                            if (jobStatus === "paused" || jobStatus === "interrupted"
                                                    || jobStatus === "failed")
                                                queueController.resume(jobId)
                                            else
                                                queueController.pause(jobId)
                                        }
                                    }
                                    Button {
                                        text: "Cancel"
                                        enabled: ["completed", "cancelled"].indexOf(jobStatus) < 0
                                        onClicked: queueController.cancel(jobId)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        Item {
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 30
                spacing: 16

                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Label {
                            text: "Candidate results"
                            color: "#f4f7fb"
                            font.pixelSize: 27
                            font.weight: Font.DemiBold
                        }
                        Label {
                            text: "Review auto-selected moments and export source-quality clips."
                            color: "#8792a5"
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Button {
                        text: "Refresh"
                        onClicked: resultsController.refresh()
                    }
                }

                Rectangle {
                    visible: resultsController.notice.length > 0
                    Layout.fillWidth: true
                    implicitHeight: visible ? 44 : 0
                    radius: 9
                    color: resultsController.noticeIsError ? "#3c222a" : "#183429"
                    Label {
                        anchors.centerIn: parent
                        width: parent.width - 30
                        text: resultsController.notice
                        color: resultsController.noticeIsError ? "#ff9aa6" : "#7de4a9"
                        elide: Text.ElideMiddle
                        horizontalAlignment: Text.AlignHCenter
                    }
                }

                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    Column {
                        width: parent.width
                        spacing: 10

                        Repeater {
                            model: candidatesModel
                            delegate: Rectangle {
                                required property string candidateId
                                required property string candidateJobId
                                required property string candidateSource
                                required property string candidateTitle
                                required property string candidateTime
                                required property real candidateScore
                                required property real candidateDuration
                                required property string candidateRationale
                                required property bool candidatePreselected
                                required property string candidateStatus
                                required property int candidateSpanCount
                                width: parent.width
                                height: 128
                                radius: 12
                                color: "#111720"
                                border.width: candidatePreselected ? 1 : 0
                                border.color: "#426fae"

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 16
                                    spacing: 14

                                    Rectangle {
                                        Layout.preferredWidth: 54
                                        Layout.preferredHeight: 54
                                        radius: 27
                                        color: "#1d2b40"
                                        Label {
                                            anchors.centerIn: parent
                                            text: Math.round(candidateScore * 100) + "%"
                                            color: "#76afff"
                                            font.weight: Font.Bold
                                        }
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 4
                                        RowLayout {
                                            Label {
                                                text: candidateTitle
                                                color: "#f4f7fb"
                                                font.pixelSize: 14
                                                font.weight: Font.DemiBold
                                            }
                                            Label {
                                                visible: candidatePreselected
                                                text: "AUTO SELECTED"
                                                color: "#76afff"
                                                font.pixelSize: 9
                                                font.weight: Font.Bold
                                            }
                                        }
                                        Label {
                                            text: candidateTime + "  /  "
                                                  + candidateDuration.toFixed(1) + "s output  /  "
                                                  + candidateSpanCount + " span(s)"
                                            color: "#a2adbd"
                                            font.pixelSize: 11
                                        }
                                        Label {
                                            Layout.fillWidth: true
                                            text: candidateRationale
                                            color: "#69778c"
                                            font.pixelSize: 11
                                            elide: Text.ElideRight
                                        }
                                        Label {
                                            Layout.fillWidth: true
                                            text: candidateSource
                                            color: "#596579"
                                            font.pixelSize: 10
                                            elide: Text.ElideMiddle
                                        }
                                    }

                                    Button {
                                        text: candidateStatus === "selected" ? "Selected" : "Select"
                                        onClicked: resultsController.review(candidateId, "selected")
                                    }
                                    Button {
                                        text: "Reject"
                                        onClicked: resultsController.review(candidateId, "rejected")
                                    }
                                    Button {
                                        text: candidateStatus === "exported" ? "Exported" : "Export"
                                        enabled: !resultsController.exporting
                                                 && candidateStatus !== "exported"
                                        onClicked: resultsController.exportCandidate(candidateId)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        Item {
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 30
                spacing: 16

                ColumnLayout {
                    Label {
                        text: "Reusable profiles"
                        color: "#f4f7fb"
                        font.pixelSize: 27
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: "Defaults apply to new jobs. Queue reuse can copy content, analysis, or both."
                        color: "#8792a5"
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 286
                    radius: 12
                    color: "#141a24"
                    border.width: 1
                    border.color: "#202939"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 10

                        Label {
                            text: "DEFAULT CONTENT PREFERENCE"
                            color: "#697589"
                            font.pixelSize: 10
                            font.weight: Font.Bold
                        }
                        TextArea {
                            id: preferenceEditor
                            Layout.fillWidth: true
                            Layout.preferredHeight: 80
                            text: profilesController.preference
                            wrapMode: TextEdit.Wrap
                            placeholderText: "Describe the moments you want the AI to favor."
                        }
                        RowLayout {
                            Label { text: "Language"; color: "#aab3c2" }
                            ComboBox {
                                id: languageSelector
                                model: ["auto", "en", "el"]
                                currentIndex: Math.max(
                                    0,
                                    model.indexOf(profilesController.language)
                                )
                            }
                            Label { text: "Min seconds"; color: "#aab3c2" }
                            SpinBox {
                                id: targetMinEditor
                                from: 5
                                to: 300
                                value: profilesController.targetMinSeconds
                            }
                            Label { text: "Max seconds"; color: "#aab3c2" }
                            SpinBox {
                                id: targetMaxEditor
                                from: 10
                                to: 600
                                value: profilesController.targetMaxSeconds
                            }
                            Label { text: "Candidates"; color: "#aab3c2" }
                            SpinBox {
                                id: maxCandidatesEditor
                                from: 1
                                to: 100
                                value: profilesController.maxCandidates
                            }
                            Label { text: "Auto select"; color: "#aab3c2" }
                            SpinBox {
                                id: autoSelectEditor
                                from: 0
                                to: 100
                                value: profilesController.autoPreselectCount
                            }
                            Item { Layout.fillWidth: true }
                            Button {
                                text: "Save default"
                                onClicked: profilesController.saveContentProfile(
                                    preferenceEditor.text,
                                    languageSelector.currentText,
                                    targetMinEditor.value,
                                    targetMaxEditor.value,
                                    maxCandidatesEditor.value,
                                    autoSelectEditor.value
                                )
                            }
                        }
                        Label {
                            text: profilesController.notice
                            color: "#7de4a9"
                        }
                    }
                }

                Label {
                    text: "ANALYSIS PRESETS"
                    color: "#697589"
                    font.pixelSize: 10
                    font.weight: Font.Bold
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 12

                    Repeater {
                        model: [
                            {
                                "name": "QUICK",
                                "modelName": "Whisper small",
                                "signals": "Transcript + audio / no frames",
                                "purpose": "Fast first pass and low memory use."
                            },
                            {
                                "name": "BALANCED",
                                "modelName": "Whisper large-v3-turbo",
                                "signals": "Transcript + audio + 360p frame sampling",
                                "purpose": "Default quality/performance profile."
                            },
                            {
                                "name": "DEEP",
                                "modelName": "Whisper large-v3-turbo",
                                "signals": "Dense signals + candidate-only vision",
                                "purpose": "Slower reranking for the strongest review set."
                            }
                        ]
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 12
                            color: modelData.name === "BALANCED" ? "#17243a" : "#111720"
                            border.width: 1
                            border.color: modelData.name === "BALANCED" ? "#3c6ca8" : "#1c2635"

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 18
                                spacing: 8
                                Label {
                                    text: modelData.name
                                    color: modelData.name === "BALANCED" ? "#76afff" : "#f4f7fb"
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }
                                Label { text: modelData.modelName; color: "#c1cad8" }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.signals
                                    color: "#8a96a9"
                                    wrapMode: Text.WordWrap
                                }
                                Item { Layout.fillHeight: true }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.purpose
                                    color: "#657188"
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                }
            }
        }

        Item {
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 30
                spacing: 18

                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Label {
                            text: "Resource monitor"
                            color: "#f4f7fb"
                            font.pixelSize: 27
                            font.weight: Font.DemiBold
                        }
                        Label {
                            text: resourceController.thermalStatus
                            color: "#8792a5"
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Button {
                        text: window.monitorVisible ? "Hide compact panel" : "Show compact panel"
                        onClicked: window.monitorVisible = !window.monitorVisible
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 3
                    columnSpacing: 12
                    rowSpacing: 12

                    Repeater {
                        model: [
                            {
                                "title": "CPU",
                                "primary": window.metric(
                                    resourceController.snapshot.system_cpu_percent, 1, "%"
                                ) + " system",
                                "secondary": window.metric(
                                    resourceController.snapshot.app_cpu_percent, 1, "%"
                                ) + " app / " + window.metric(
                                    resourceController.snapshot.cpu_current_mhz, 0, " MHz"
                                ),
                                "detail": resourceController.snapshot.physical_cores
                                          + " cores / "
                                          + resourceController.snapshot.logical_cores
                                          + " threads / "
                                          + window.metric(
                                              resourceController.snapshot.cpu_temperature_c,
                                              0,
                                              " °C"
                                          )
                            },
                            {
                                "title": "Memory",
                                "primary": window.metric(
                                    resourceController.snapshot.system_ram_used_gib, 1, " GiB"
                                ) + " used",
                                "secondary": window.metric(
                                    resourceController.snapshot.app_ram_gib, 2, " GiB"
                                ) + " app",
                                "detail": window.metric(
                                    resourceController.snapshot.system_ram_total_gib, 1, " GiB"
                                ) + " installed"
                            },
                            {
                                "title": "GPU",
                                "primary": window.metric(
                                    resourceController.snapshot.gpu_percent, 0, "%"
                                ) + " / " + window.metric(
                                    resourceController.snapshot.gpu_temperature_c, 0, " °C"
                                ),
                                "secondary": window.metric(
                                    resourceController.snapshot.gpu_clock_mhz, 0, " MHz"
                                ) + " / " + window.metric(
                                    resourceController.snapshot.gpu_power_watts, 1, " W"
                                ),
                                "detail": resourceController.snapshot.gpu_name || "Unavailable"
                            },
                            {
                                "title": "VRAM",
                                "primary": window.metric(
                                    resourceController.snapshot.gpu_vram_used_gib, 2, " GiB"
                                ) + " device",
                                "secondary": window.metric(
                                    resourceController.snapshot.app_vram_gib, 2, " GiB"
                                ) + " app + workers",
                                "detail": window.metric(
                                    resourceController.snapshot.gpu_vram_total_gib, 2, " GiB"
                                ) + " total"
                            },
                            {
                                "title": "GPU clocks",
                                "primary": window.metric(
                                    resourceController.snapshot.gpu_clock_mhz, 0, " MHz"
                                ) + " graphics",
                                "secondary": window.metric(
                                    resourceController.snapshot.gpu_memory_clock_mhz, 0, " MHz"
                                ) + " memory",
                                "detail": window.metric(
                                    resourceController.snapshot.gpu_power_limit_watts, 0, " W"
                                ) + " power limit"
                            },
                            {
                                "title": "App I/O",
                                "primary": window.metric(
                                    resourceController.snapshot.app_read_mib, 1, " MiB"
                                ) + " read",
                                "secondary": window.metric(
                                    resourceController.snapshot.app_write_mib, 1, " MiB"
                                ) + " written",
                                "detail": "Current process tree"
                            }
                        ]

                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 122
                            radius: 12
                            color: "#141a24"
                            border.width: 1
                            border.color: "#202939"

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 15
                                Label {
                                    text: modelData.title.toUpperCase()
                                    color: "#697589"
                                    font.pixelSize: 10
                                    font.weight: Font.Bold
                                }
                                Label {
                                    text: modelData.primary
                                    color: "#f4f7fb"
                                    font.pixelSize: 18
                                }
                                Label { text: modelData.secondary; color: "#9ca7b8" }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.detail
                                    color: "#657188"
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 12
                    color: "#111720"
                    border.width: 1
                    border.color: "#1c2635"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 12
                        Label {
                            text: "THERMAL AND MEMORY POLICY"
                            color: "#697589"
                            font.pixelSize: 10
                            font.weight: Font.Bold
                        }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            text: "A temperature must remain over its limit for the grace "
                                  + "period before Local Clip AI pauses. Work resumes only "
                                  + "after temperatures stay below the resume point."
                            color: "#8792a5"
                        }
                        RowLayout {
                            Label { text: "GPU pause °C"; color: "#aab3c2" }
                            SpinBox {
                                from: 50
                                to: 110
                                value: resourceController.gpuPauseTemperature
                                onValueModified: resourceController.setGpuPauseTemperature(value)
                            }
                            Label { text: "CPU pause °C"; color: "#aab3c2" }
                            SpinBox {
                                from: 50
                                to: 110
                                value: resourceController.cpuPauseTemperature
                                onValueModified: resourceController.setCpuPauseTemperature(value)
                            }
                            Label { text: "Resume °C"; color: "#aab3c2" }
                            SpinBox {
                                from: 40
                                to: 100
                                value: resourceController.resumeTemperature
                                onValueModified: resourceController.setResumeTemperature(value)
                            }
                            Label { text: "Grace sec"; color: "#aab3c2" }
                            SpinBox {
                                from: 10
                                to: 1800
                                value: resourceController.graceSeconds
                                editable: true
                                onValueModified: resourceController.setGraceSeconds(value)
                            }
                            Label { text: "VRAM soft GiB"; color: "#aab3c2" }
                            SpinBox {
                                from: 1
                                to: 64
                                value: resourceController.vramSoftLimitGib
                                onValueModified: resourceController.setVramSoftLimitGib(value)
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            text: resourceController.snapshot.cpu_temperature_c === null
                                  || resourceController.snapshot.cpu_temperature_c === undefined
                                  ? "CPU package temperature is unavailable through Windows "
                                    + "on this machine; GPU thermal protection remains active."
                                  : "CPU and GPU thermal protection are active."
                            color: "#f5bd58"
                            font.pixelSize: 11
                        }
                        Item { Layout.fillHeight: true }
                    }
                }
            }
        }

        Item {
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 30
                spacing: 18

                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        spacing: 4
                        Label {
                            text: "System diagnostics"
                            color: "#f4f7fb"
                            font.pixelSize: 27
                            font.weight: Font.DemiBold
                        }
                        Label {
                            text: "Validate hardware, portable media tools, storage, and database."
                            color: "#8e99ab"
                            font.pixelSize: 13
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Button {
                        text: diagnosticsController.running ? "Checking..." : "Run diagnostics"
                        enabled: !diagnosticsController.running
                        onClicked: diagnosticsController.refresh()
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 82
                    radius: 14
                    color: "#141a24"
                    border.width: 1
                    border.color: "#202939"

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 18
                        Rectangle {
                            Layout.preferredWidth: 13
                            Layout.preferredHeight: 13
                            radius: 7
                            color: window.statusColor(diagnosticsController.overallStatus)
                        }
                        Label {
                            text: diagnosticsController.summary
                            color: "#f4f7fb"
                            font.pixelSize: 15
                        }
                        Item { Layout.fillWidth: true }
                        BusyIndicator {
                            running: diagnosticsController.running
                            visible: running
                        }
                    }
                }

                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    Column {
                        width: parent.width
                        spacing: 10

                        Repeater {
                            model: diagnosticsModel
                            delegate: Rectangle {
                                required property string checkName
                                required property string checkStatus
                                required property string checkSummary
                                width: parent.width
                                height: 70
                                radius: 11
                                color: "#111720"
                                border.width: 1
                                border.color: "#1c2635"

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 16
                                    Rectangle {
                                        Layout.preferredWidth: 10
                                        Layout.preferredHeight: 10
                                        radius: 5
                                        color: window.statusColor(checkStatus)
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: checkName; color: "#f4f7fb" }
                                        Label {
                                            Layout.fillWidth: true
                                            text: checkSummary
                                            color: "#8792a5"
                                            elide: Text.ElideRight
                                        }
                                    }
                                    Label {
                                        text: checkStatus.toUpperCase()
                                        color: window.statusColor(checkStatus)
                                        font.pixelSize: 10
                                        font.weight: Font.Bold
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        Item {
            ColumnLayout {
                anchors.centerIn: parent
                Label { text: "Settings"; color: "#f4f7fb"; font.pixelSize: 28 }
                Label {
                    text: "Runtime directory: " + diagnosticsController.dataRoot
                    color: "#8792a5"
                }
            }
        }
    }

    Rectangle {
        id: compactMonitor
        visible: window.monitorVisible
        width: 330
        anchors.top: noticeBanner.visible ? noticeBanner.bottom : parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        color: "#121823"
        border.width: 1
        border.color: "#293449"
        z: 8

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: "LIVE RESOURCES"
                    color: "#f4f7fb"
                    font.weight: Font.Bold
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "Close"
                    flat: true
                    onClicked: window.monitorVisible = false
                }
            }
            Label {
                text: "CPU  " + window.metric(
                    resourceController.snapshot.system_cpu_percent, 1, "%"
                ) + " system / " + window.metric(
                    resourceController.snapshot.app_cpu_percent, 1, "%"
                ) + " app"
                color: "#c3ccda"
            }
            Label {
                text: "CPU clock  " + window.metric(
                    resourceController.snapshot.cpu_current_mhz, 0, " MHz"
                )
                color: "#8895a8"
            }
            Label {
                text: "CPU temp  " + window.metric(
                    resourceController.snapshot.cpu_temperature_c, 0, " °C"
                )
                color: "#8895a8"
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: "#263043"
            }
            Label {
                text: "RAM  " + window.metric(
                    resourceController.snapshot.system_ram_used_gib, 1, " GiB"
                ) + " system / " + window.metric(
                    resourceController.snapshot.app_ram_gib, 2, " GiB"
                ) + " app"
                color: "#c3ccda"
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: "#263043"
            }
            Label {
                text: "GPU  " + window.metric(
                    resourceController.snapshot.gpu_percent, 0, "%"
                ) + " / " + window.metric(
                    resourceController.snapshot.gpu_temperature_c, 0, " °C"
                )
                color: "#c3ccda"
            }
            Label {
                text: "GPU clock  " + window.metric(
                    resourceController.snapshot.gpu_clock_mhz, 0, " MHz"
                ) + " / " + window.metric(
                    resourceController.snapshot.gpu_power_watts, 1, " W"
                )
                color: "#8895a8"
            }
            Label {
                text: "VRAM  " + window.metric(
                    resourceController.snapshot.gpu_vram_used_gib, 2, " GiB"
                ) + " device / " + window.metric(
                    resourceController.snapshot.app_vram_gib, 2, " GiB"
                ) + " app"
                color: resourceController.snapshot.vram_pressure ? "#f5bd58" : "#8895a8"
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: "#263043"
            }
            Label {
                Layout.fillWidth: true
                text: resourceController.thermalStatus
                wrapMode: Text.WordWrap
                color: "#8fb9f5"
            }
            Item { Layout.fillHeight: true }
            Label {
                text: queueController.running
                      ? "Sleep prevention: ACTIVE"
                      : "Sleep prevention: waiting"
                color: queueController.running ? "#51d88a" : "#657188"
            }
        }
    }
}
