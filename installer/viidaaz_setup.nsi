; viidaaz Setup — NSIS installer (per-user, no admin required)
; Build: makensis installer\viidaaz_setup.nsi   (run from the project root)
; Output: installer\viidaaz-Setup.exe

!define APPNAME "viidaaz"
!define APPVERSION "2.5"
!define PUBLISHER "JonamMadeda"
!define EXE "viidaaz.exe"
!define SETUP "viidaaz-Setup.exe"

Name "${APPNAME} ${APPVERSION}"
OutFile "${SETUP}"
InstallDir "$LOCALAPPDATA\${APPNAME}"
Icon "..\assets\viidaaz.ico"
UninstallIcon "..\assets\viidaaz.ico"
RequestExecutionLevel user
ShowInstDetails nevershow

Page directory
Page instfiles

Section "Application" SEC_APP
  SectionIn RO
  SetOutPath "$INSTDIR"
  File "..\dist\${EXE}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ; Add/Remove Programs entry (current user)
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" \
    "DisplayName" "${APPNAME} ${APPVERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" \
    "DisplayVersion" "${APPVERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" \
    "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" \
    "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" \
    "DisplayIcon" "$INSTDIR\${EXE}"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" \
    "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" \
    "NoRepair" 1
SectionEnd

Section "Start Menu shortcut" SEC_STARTMENU
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Desktop shortcut" SEC_DESKTOP
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"
SectionEnd
