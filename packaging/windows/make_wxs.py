"""Generate the WiX v5 source of the Monkey Viewer MSI from the PyInstaller output.

    python packaging/windows/make_wxs.py --src dist/MonkeyViewer --out build/msi

Then (Windows, .NET SDK):
    dotnet tool install --global wix --version 5.0.2
    wix extension add -g WixToolset.UI.wixext/5.0.2
    wix build build/msi/MonkeyViewer.wxs -arch x64 -ext WixToolset.UI.wixext -o release/MonkeyViewer-<ver>-x64.msi

The MSI is per-machine (Program Files, admin rights), suitable for Group Policy software installation,
Intune or SCCM, and replaces any other version in place (MajorUpgrade with AllowDowngrades, fixed UpgradeCode). Silent install:
    msiexec /i MonkeyViewer-<ver>-x64.msi /qn
"""

import argparse
import hashlib
import os
import sys
import uuid
# saxutils is used only to *escape* text we write, never to parse input
from xml.sax.saxutils import quoteattr  # nosec B406

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from viewer import app_info, formats  # noqa: E402
from viewer.winutil import PROGIDS, _progid_for  # noqa: E402

NAMESPACE = uuid.UUID("7e857ef2-7002-4b30-b232-fd3e7fa2b8ed")   # fixed: component GUIDs stay stable per path
EVENT_MESSAGE_FILE = r"%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\EventLogMessages.dll"


def ident(prefix, rel):
    return f"{prefix}{hashlib.sha256(rel.lower().encode('utf-8')).hexdigest()[:30]}"


def guid(rel):
    return "{" + str(uuid.uuid5(NAMESPACE, rel.lower().replace("\\", "/"))).upper() + "}"


def rtf(text):
    out = []
    for ch in text:
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\par\n")
        elif ord(ch) > 127:
            code = ord(ch)
            out.append(f"\\u{code if code < 32768 else code - 65536}?")
        else:
            out.append(ch)
    return "{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Segoe UI;}}\\viewkind4\\uc1\\f0\\fs18 " + "".join(out) + "}"


def build(src, out_dir):
    src = os.path.abspath(src)
    exe = os.path.join(src, "MonkeyViewer.exe")
    if not os.path.exists(exe):
        raise SystemExit(f"{exe} not found - run PyInstaller first")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(ROOT, "LICENSE.txt"), encoding="utf-8") as fh:
        license_rtf = os.path.join(out_dir, "License.rtf")
        with open(license_rtf, "w", encoding="ascii") as out:
            out.write(rtf(fh.read()))

    # extra admin material installed next to the program
    extras = []
    for folder in ("deploy",):
        base = os.path.join(ROOT, folder)
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                full = os.path.join(dirpath, name)
                extras.append((os.path.join("Admin", os.path.relpath(full, base)), full))

    tree = {}                                   # dir rel path -> list of (file rel path, source)
    for dirpath, _dirs, files in os.walk(src):
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, src)
            tree.setdefault(os.path.dirname(rel), []).append((rel, full))
    for rel, full in extras:
        tree.setdefault(os.path.dirname(rel), []).append((rel, full))
    for d in list(tree):                        # make sure every parent directory exists in the tree
        while d:
            d = os.path.dirname(d)
            tree.setdefault(d, [])

    def children(parent):
        return sorted(d for d in tree if d and os.path.dirname(d) == parent)

    lines, comps = [], []

    def emit_dir(rel, indent):
        pad = " " * indent
        for f_rel, full in tree.get(rel, []):
            cid = "MonkeyViewerExeComponent" if f_rel == "MonkeyViewer.exe" else ident("c", f_rel)
            fid = "MonkeyViewerExe" if f_rel == "MonkeyViewer.exe" else ident("f", f_rel)
            comps.append(cid)
            lines.append(f'{pad}<Component Id="{cid}" Guid="{guid(f_rel)}">')
            if f_rel == "MonkeyViewer.exe":
                lines.append(f'{pad}  <File Id="{fid}" Source={quoteattr(full)} KeyPath="yes">')
                lines.append(f'{pad}    <Shortcut Id="StartMenuShortcut" Directory="ProgramMenuFolder" '
                             f'Name={quoteattr(app_info.NAME)} Description={quoteattr(app_info.DESCRIPTION)} '
                             f'WorkingDirectory="INSTALLFOLDER" Icon="MonkeyViewer.ico" Advertise="yes" />')
                lines.append(f'{pad}    <Shortcut Id="DesktopShortcut" Directory="DesktopFolder" '
                             f'Name={quoteattr(app_info.NAME)} Description={quoteattr(app_info.DESCRIPTION)} '
                             f'WorkingDirectory="INSTALLFOLDER" Icon="MonkeyViewer.ico" Advertise="yes" />')
                lines.append(f'{pad}  </File>')
            else:
                lines.append(f'{pad}  <File Id="{fid}" Source={quoteattr(full)} KeyPath="yes" />')
            lines.append(f'{pad}</Component>')
        for sub in children(rel):
            lines.append(f'{pad}<Directory Id="{ident("d", sub)}" Name={quoteattr(os.path.basename(sub))}>')
            emit_dir(sub, indent + 2)
            lines.append(f'{pad}</Directory>')

    emit_dir("", 8)
    comp_refs = "\n".join(f'      <ComponentRef Id="{c}" />' for c in comps)

    # Machine-wide ProgIDs + "Default apps" capabilities: Monkey Viewer becomes *available* for its file types
    # (Settings > Default apps, DISM default-association XML). No extension is associated by the MSI itself.
    command = quoteattr('"[INSTALLFOLDER]MonkeyViewer.exe" "%1"')
    exe_icon = '"[INSTALLFOLDER]MonkeyViewer.exe",0'
    ico_files = {os.path.basename(rel).lower(): rel for rels in tree.values() for rel, _full in rels
                 if rel.lower().endswith(".ico") and os.path.basename(os.path.dirname(rel)).lower() == "icons"}
    reg = []
    for suffix, (friendly, _cats) in PROGIDS.items():
        key = f"Software\\Classes\\{app_info.APP_ID}.{suffix}"
        rel = ico_files.get(f"{suffix}.ico")          # each file type has its own icon (tools/make_icons.py)
        icon = quoteattr("[INSTALLFOLDER]" + rel.replace("/", "\\") + ",0" if rel else exe_icon)
        reg += [f'      <RegistryKey Root="HKLM" Key="{key}">',
                f'        <RegistryValue Type="string" Value={quoteattr(friendly)} />',
                f'        <RegistryValue Name="FriendlyTypeName" Type="string" Value={quoteattr(friendly)} />',
                f'        <RegistryValue Key="DefaultIcon" Type="string" Value={icon} />',
                f'        <RegistryValue Key="shell\\open\\command" Type="string" Value={command} />',
                '      </RegistryKey>']
    caps = f"Software\\{app_info.APP_ID}\\Capabilities"
    reg += [f'      <RegistryKey Root="HKLM" Key="{caps}">',
            f'        <RegistryValue Name="ApplicationName" Type="string" Value={quoteattr(app_info.NAME)} />',
            f'        <RegistryValue Name="ApplicationDescription" Type="string" Value={quoteattr(app_info.DESCRIPTION)} />',
            '      </RegistryKey>']
    assoc_lines = [f'        <RegistryValue Name="{ext}" Type="string" Value="{_progid_for(ext, cat)}" />'
                   for ext, cat in sorted(formats.association_extensions().items())]
    reg += [f'      <RegistryKey Root="HKLM" Key="{caps}\\FileAssociations">'] + assoc_lines + ['      </RegistryKey>']
    reg += ['      <RegistryValue Root="HKLM" Key="Software\\RegisteredApplications" '
            f'Name={quoteattr(app_info.NAME)} Type="string" Value="{caps}" KeyPath="yes" />']
    registration = "\n".join(reg)
    body = "\n".join(lines)
    wxs = f'''<?xml version="1.0" encoding="utf-8"?>
<!-- Generated by packaging/windows/make_wxs.py - do not edit by hand. -->
<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs" xmlns:ui="http://wixtoolset.org/schemas/v4/wxs/ui">
  <Package Name={quoteattr(app_info.NAME)} Manufacturer={quoteattr(app_info.PUBLISHER)}
           Version="{app_info.VERSION}" UpgradeCode="{app_info.UPGRADE_CODE}" Scope="perMachine" Language="1033">
    <SummaryInformation Description={quoteattr(f"{app_info.NAME} {app_info.VERSION}")}
                        Manufacturer={quoteattr(app_info.PUBLISHER)} />
    <!-- any other version is replaced in place, also the internal 3.x / 4.x test builds numbered above 1.0 -->
    <MajorUpgrade AllowDowngrades="yes" />
    <!-- after installing or removing by hand, Windows offers to restart (Yes / later); silent installs (GPO,
         Intune, SCCM: msiexec /qn) never restart, and REBOOT=ReallySuppress turns it off as well -->
    <InstallExecuteSequence>
      <ScheduleReboot After="InstallFinalize" Condition="UILevel &gt; 2 AND NOT UPGRADINGPRODUCTCODE" />
    </InstallExecuteSequence>
    <MediaTemplate EmbedCab="yes" CompressionLevel="high" />

    <Icon Id="MonkeyViewer.ico" SourceFile={quoteattr(os.path.join(ROOT, "monkeyviewer.ico"))} />
    <Property Id="ARPPRODUCTICON" Value="MonkeyViewer.ico" />
    <Property Id="ARPCOMMENTS" Value={quoteattr(app_info.DESCRIPTION)} />
    <WixVariable Id="WixUILicenseRtf" Value={quoteattr(license_rtf)} />
    <WixVariable Id="WixUIDialogBmp" Value={quoteattr(os.path.join(ROOT, "packaging", "windows", "dialog.bmp"))} />
    <WixVariable Id="WixUIBannerBmp" Value={quoteattr(os.path.join(ROOT, "packaging", "windows", "banner.bmp"))} />
    <!-- Welcome, licence, choice of folder, install: usable by hand; msiexec /qn skips all of it -->
    <ui:WixUI Id="WixUI_InstallDir" InstallDirectory="INSTALLFOLDER" />

    <StandardDirectory Id="ProgramFiles64Folder">
      <Directory Id="INSTALLFOLDER" Name={quoteattr(app_info.NAME)}>
{body}
      </Directory>
    </StandardDirectory>
    <StandardDirectory Id="ProgramMenuFolder" />
    <StandardDirectory Id="DesktopFolder" />

    <!-- Event Log source for the EventLog audit policy -->
    <Component Id="EventLogSource" Directory="INSTALLFOLDER" Guid="{guid("eventlog-source")}">
      <RegistryKey Root="HKLM" Key="SYSTEM\\CurrentControlSet\\Services\\EventLog\\Application\\{app_info.APP_ID}">
        <RegistryValue Name="EventMessageFile" Type="expandable" Value="{EVENT_MESSAGE_FILE}" KeyPath="yes" />
        <RegistryValue Name="TypesSupported" Type="integer" Value="7" />
      </RegistryKey>
    </Component>

    <Component Id="Registration" Directory="INSTALLFOLDER" Guid="{guid("registration-progids")}">
{registration}
    </Component>

    <Feature Id="Main" Title={quoteattr(app_info.NAME)} Level="1">
{comp_refs}
      <ComponentRef Id="EventLogSource" />
      <ComponentRef Id="Registration" />
    </Feature>
  </Package>
</Wix>
'''
    path = os.path.join(out_dir, "MonkeyViewer.wxs")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(wxs)
    print(f"{path}: {len(comps)} files")
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--src", default=os.path.join(ROOT, "dist", "MonkeyViewer"))
    p.add_argument("--out", default=os.path.join(ROOT, "build", "msi"))
    a = p.parse_args()
    build(a.src, a.out)


if __name__ == "__main__":
    main()
