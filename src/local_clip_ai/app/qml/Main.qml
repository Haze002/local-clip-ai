import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1180
    height: 760
    minimumWidth: 920
    minimumHeight: 620
    visible: true
    title: "Local Clip AI"
    color: "#0b0d12"

    function statusColor(status) {
        if (status === "pass") return "#51d88a"
        if (status === "warn") return "#f5bd58"
        if (status === "fail") return "#ff6b7a"
        return "#8792a5"
    }

    function statusBackground(status) {
        if (status === "pass") return "#183429"
        if (status === "warn") return "#3b3020"
        if (status === "fail") return "#3c222a"
        return "#202735"
    }

    Rectangle {
        id: sidebar
        width: 220
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        color: "#10141c"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 14

            Label {
                text: "LOCAL CLIP AI"
                color: "#f4f7fb"
                font.pixelSize: 19
                font.weight: Font.DemiBold
                Layout.bottomMargin: 22
            }

            Repeater {
                model: ["Diagnostics", "Queue", "Profiles", "Results", "Settings"]
                delegate: Rectangle {
                    required property string modelData
                    Layout.fillWidth: true
                    implicitHeight: 42
                    radius: 10
                    color: modelData === "Diagnostics" ? "#232b3a" : "transparent"

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.leftMargin: 14
                        text: modelData
                        color: modelData === "Diagnostics" ? "#ffffff" : "#8792a5"
                        font.pixelSize: 14
                    }
                }
            }

            Item { Layout.fillHeight: true }

            Label {
                text: "MILESTONE 0"
                color: "#697589"
                font.pixelSize: 11
                font.letterSpacing: 1.4
            }
            Label {
                text: "Foundation validation"
                color: "#aab3c2"
                font.pixelSize: 12
            }
        }
    }

    ColumnLayout {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: sidebar.right
        anchors.right: parent.right
        anchors.margins: 30
        spacing: 20

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
                    text: "Validate the machine before installing the AI pipeline."
                    color: "#8e99ab"
                    font.pixelSize: 14
                }
            }

            Item { Layout.fillWidth: true }

            Button {
                text: diagnosticsController.running ? "Checking…" : "Run diagnostics"
                enabled: !diagnosticsController.running
                onClicked: diagnosticsController.refresh()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 94
            radius: 14
            color: "#141a24"
            border.width: 1
            border.color: "#202939"

            RowLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 16

                Rectangle {
                    width: 48
                    height: 48
                    radius: 24
                    color: window.statusBackground(diagnosticsController.overallStatus)

                    Rectangle {
                        width: 13
                        height: 13
                        radius: 7
                        anchors.centerIn: parent
                        color: window.statusColor(diagnosticsController.overallStatus)
                    }
                }

                ColumnLayout {
                    Label {
                        text: diagnosticsController.overallStatus.toUpperCase()
                        color: window.statusColor(diagnosticsController.overallStatus)
                        font.pixelSize: 12
                        font.weight: Font.Bold
                        font.letterSpacing: 1.2
                    }
                    Label {
                        text: diagnosticsController.summary
                        color: "#f4f7fb"
                        font.pixelSize: 17
                    }
                }

                Item { Layout.fillWidth: true }

                BusyIndicator {
                    running: diagnosticsController.running
                    visible: running
                }
            }
        }

        Label {
            text: "FOUNDATION CHECKS"
            color: "#697589"
            font.pixelSize: 11
            font.letterSpacing: 1.4
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
                        height: 76
                        radius: 12
                        color: "#111720"
                        border.width: 1
                        border.color: "#1c2635"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 18
                            anchors.rightMargin: 18
                            spacing: 14

                            Rectangle {
                                width: 10
                                height: 10
                                radius: 5
                                color: window.statusColor(checkStatus)
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4

                                Label {
                                    text: checkName
                                    color: "#f4f7fb"
                                    font.pixelSize: 14
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    text: checkSummary
                                    color: "#8792a5"
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                            }

                            Label {
                                text: checkStatus.toUpperCase()
                                color: window.statusColor(checkStatus)
                                font.pixelSize: 11
                                font.weight: Font.Bold
                                font.letterSpacing: 1.0
                            }
                        }
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            text: "Runtime data: " + diagnosticsController.dataRoot
            color: "#5f6b7e"
            font.pixelSize: 11
            elide: Text.ElideMiddle
        }
    }
}
