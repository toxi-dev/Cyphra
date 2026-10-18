; This Source Code Form is subject to the Mozilla Public License, v. 2.0.
; See https://mozilla.org/MPL/2.0/.
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!ifdef HOME_EDITION
  !define COMPANY_NAME "Cyphra"
  !define APP_NAME "Cyphra Home"
  !define INSTALL_FOLDER "CyphraHome"
  !define SETTINGS_KEY "Software\CyphraHome"
  !define UNINSTALL_KEY "CyphraHome"
  !define SHORTCUT_FOLDER "Cyphra Home"
!else ifdef PUBLIC_EDITION
  !define COMPANY_NAME "Cyphra"
  !define APP_NAME "Cyphra"
  !define INSTALL_FOLDER "CyphraPublic"
  !define SETTINGS_KEY "Software\CyphraPublic"
  !define UNINSTALL_KEY "CyphraPublic"
  !define SHORTCUT_FOLDER "Cyphra Public"
!else
  !define COMPANY_NAME "Byte Team"
  !define APP_NAME "Cyphra Byte Team"
  !define INSTALL_FOLDER "Cyphra"
  !define SETTINGS_KEY "Software\ByteTeam\Cyphra"
  !define UNINSTALL_KEY "ByteTeamCyphra"
  !define SHORTCUT_FOLDER "Cyphra"
!endif
Name "${APP_NAME}"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\${INSTALL_FOLDER}"
InstallDirRegKey HKCU "${SETTINGS_KEY}" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
CRCCheck force
ShowInstDetails show
ShowUninstDetails show
BrandingText "${COMPANY_NAME}"
VIProductVersion "${RELEASE_VERSION}.0"
VIAddVersionKey "ProductName" "Cyphra"
VIAddVersionKey "CompanyName" "${COMPANY_NAME}"
VIAddVersionKey "FileDescription" "Cyphra native Gecko browser installer"
VIAddVersionKey "FileVersion" "${RELEASE_VERSION}"
VIAddVersionKey "LegalCopyright" "Copyright 2026 Cyphra contributors"
Icon "${ICON_FILE}"
UninstallIcon "${ICON_FILE}"
!define MUI_ABORTWARNING
!define MUI_ICON "${ICON_FILE}"
!define MUI_UNICON "${ICON_FILE}"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${LICENSE_FILE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\Cyphra.exe"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Var UpdateStage
Var UpdateResult

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "Cyphra requires 64-bit Windows."
    Abort
  ${EndIf}
  SetShellVarContext current
  ReadRegStr $0 HKCU "${SETTINGS_KEY}" "InstallLocation"
!ifndef PUBLIC_EDITION
!ifndef HOME_EDITION
  ${If} $0 == ""
    ReadRegStr $0 HKCU "Software\eed7efae-7f8c-5605-9829-b5b48517d4fc" "InstallLocation"
    ${If} $0 != ""
      StrCpy $INSTDIR $0
    ${EndIf}
  ${EndIf}
!endif
!endif
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File /oname=Cyphra-maintenance.exe "${MAINTENANCE_HELPER}"
FunctionEnd

Function un.onInit
  ClearErrors
  ExecWait '"$INSTDIR\Cyphra-maintenance.exe" --check "$INSTDIR" "${RELEASE_VERSION}"' $UpdateResult
  IfErrors un.helper_failed
  ${If} $UpdateResult != 0
    Abort
  ${EndIf}
  Return
  un.helper_failed:
    MessageBox MB_ICONSTOP "Cyphra could not run its local maintenance helper. Reinstall this release to repair the application before uninstalling it. Your profile was left unchanged."
    Abort
FunctionEnd

Section "Cyphra" SEC_MAIN
  SetShellVarContext current
  ; All release files are extracted beside the current installation first.
  ; The native helper checks running processes, versions and SHA-256 hashes,
  ; then swaps the whole application folder. Profiles live elsewhere.
  ClearErrors
  ExecWait '"$PLUGINSDIR\Cyphra-maintenance.exe" --check "$INSTDIR" "${RELEASE_VERSION}"' $UpdateResult
  IfErrors helper_failed
  ${If} $UpdateResult != 0
    Abort
  ${EndIf}
  System::Call 'kernel32::GetCurrentProcessId() i.r0'
  StrCpy $UpdateStage "$INSTDIR.__cyphra-update-$0"
  IfFileExists "$UpdateStage\*" staging_exists
  SetOutPath "$UpdateStage"
  ClearErrors
  File /r "${STAGE_DIR}\*"
  IfErrors install_failed
  ; Standard NSIS generation happens during installation. Building on Linux
  ; never executes a Windows stub or invokes Wine.
  WriteUninstaller "$UpdateStage\Uninstall Cyphra.exe"
  IfErrors install_failed
  ; Leave the staging directory as the process working directory before it is
  ; renamed; Windows otherwise prevents its move.
  SetOutPath "$TEMP"
  ClearErrors
  ExecWait '"$PLUGINSDIR\Cyphra-maintenance.exe" --commit "$INSTDIR" "$UpdateStage" "${RELEASE_VERSION}"' $UpdateResult
  IfErrors install_failed
  ${If} $UpdateResult != 0
    RMDir /r "$UpdateStage"
    Abort
  ${EndIf}
  CreateDirectory "$SMPROGRAMS\${SHORTCUT_FOLDER}"
!ifdef HOME_EDITION
  CreateShortcut "$SMPROGRAMS\${SHORTCUT_FOLDER}\Cyphra Home.lnk" "$INSTDIR\Cyphra.exe" "" "$INSTDIR\Cyphra.exe" 0
!else
  CreateShortcut "$SMPROGRAMS\${SHORTCUT_FOLDER}\Cyphra Work.lnk" "$INSTDIR\Cyphra.exe" "--work" "$INSTDIR\Cyphra.exe" 0
  CreateShortcut "$SMPROGRAMS\${SHORTCUT_FOLDER}\Cyphra Personal.lnk" "$INSTDIR\Cyphra.exe" "--personal" "$INSTDIR\Cyphra.exe" 0
!endif
  CreateShortcut "$SMPROGRAMS\${SHORTCUT_FOLDER}\Uninstall Cyphra.lnk" "$INSTDIR\Uninstall Cyphra.exe"
  CreateShortcut "$DESKTOP\${SHORTCUT_FOLDER}.lnk" "$INSTDIR\Cyphra.exe" "" "$INSTDIR\Cyphra.exe" 0
  WriteRegStr HKCU "${SETTINGS_KEY}" "InstallLocation" "$INSTDIR"
!ifndef PUBLIC_EDITION
!ifndef HOME_EDITION
  Delete "$SMPROGRAMS\${SHORTCUT_FOLDER}\Cyphra.lnk"
  ; Remove the old prototype's obsolete uninstall registration only when it
  ; pointed at the folder this installer has successfully replaced.
  ReadRegStr $0 HKCU "Software\eed7efae-7f8c-5605-9829-b5b48517d4fc" "InstallLocation"
  ${If} $0 == $INSTDIR
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\eed7efae-7f8c-5605-9829-b5b48517d4fc"
    DeleteRegKey HKCU "Software\eed7efae-7f8c-5605-9829-b5b48517d4fc"
  ${EndIf}
!endif
!endif
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_KEY}" "DisplayVersion" "${RELEASE_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_KEY}" "Publisher" "${COMPANY_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\Cyphra.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall Cyphra.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall Cyphra.exe" /S'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_KEY}" "NoRepair" 1
  Goto install_done
  install_failed:
    SetOutPath "$TEMP"
    RMDir /r "$UpdateStage"
    MessageBox MB_ICONSTOP "Cyphra could not write its staged application files. The installed browser and its separate profile were left unchanged. Check folder permissions and free disk space before trying again."
    Abort
  staging_exists:
    MessageBox MB_ICONSTOP "A previous staging folder already exists at $UpdateStage. Move it aside before retrying. The installed browser was left unchanged."
    Abort
  helper_failed:
    MessageBox MB_ICONSTOP "Cyphra could not run its local maintenance helper. Check the installer and your Windows application policy. The current browser and profile were left unchanged."
    Abort
  install_done:
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  ; The generated list deletes only files shipped by this version. No recursive
  ; directory deletion: profiles and unexpected user files remain untouched.
  !include "${UNINSTALL_LIST}"
  Delete "$INSTDIR\Uninstall Cyphra.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\${SHORTCUT_FOLDER}.lnk"
  Delete "$SMPROGRAMS\${SHORTCUT_FOLDER}\Cyphra.lnk"
  Delete "$SMPROGRAMS\${SHORTCUT_FOLDER}\Uninstall Cyphra.lnk"
  Delete "$SMPROGRAMS\${SHORTCUT_FOLDER}\Cyphra Home.lnk"
  Delete "$SMPROGRAMS\${SHORTCUT_FOLDER}\Cyphra Work.lnk"
  Delete "$SMPROGRAMS\${SHORTCUT_FOLDER}\Cyphra Personal.lnk"
  RMDir "$SMPROGRAMS\${SHORTCUT_FOLDER}"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_KEY}"
  DeleteRegKey HKCU "${SETTINGS_KEY}"
SectionEnd
