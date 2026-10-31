"""Generate the Group Policy templates (deploy/admx) from viewer/policy.py.

    python tools/gen_admx.py

Copy MonkeyViewer.admx to \\\\<domain>\\SYSVOL\\<domain>\\Policies\\PolicyDefinitions and the .adml files to the
matching language folders (en-US, ka-GE). The policies then appear under
Computer / User Configuration > Administrative Templates > Monkey Viewer.
"""

import os
import sys
# saxutils is used only to *escape* text we write, never to parse input
from xml.sax.saxutils import escape  # nosec B406

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from viewer import app_info  # noqa: E402
from viewer.policy import CHOICES, DEFINITIONS  # noqa: E402

NS = "http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions"
KEY = app_info.POLICY_KEY

TEXT = {
    "en-US": {
        "_category": "Monkey Viewer",
        "_supported": f"Monkey Viewer {app_info.VERSION.split('.')[0]}.0 and later",
        "_desc": "Settings for Monkey Viewer, the viewer for specialist files.",
        "DisableAssociationPrompt": ("Don't ask users to choose file types",
                                     "Monkey Viewer normally asks once, on first start, which file types should open "
                                     "in it. Enable this to skip that question (for example when file types are "
                                     "deployed centrally)."),
        "DisableAssociationChanges": ("Prevent users from changing file associations",
                                      "Hides File associations and Remove all associations. Monkey Viewer then never "
                                      "changes which program opens which file type."),
        "DisableExternalTools": ("Don't start helper programs",
                                 "Monkey Viewer never starts GnuPG, DjVuLibre or ODA File Converter, even when they "
                                 "are installed. Their file types are shown as information only."),
        "DisableDecryption": ("Don't decrypt files",
                              "Encrypted files (.enc, .gpg, .p7m enveloped data...) are identified and described, "
                              "but never decrypted. Signature checks remain available."),
        "ReadOnly": ("View-only mode",
                     "Nothing can be saved or exported from Monkey Viewer: Save, Save As, Export and PDF tools that "
                     "write files are blocked."),
        "DisableWeather": ("Turn off the weather forecast",
                           "The weather corner of the status bar is hidden and Monkey Viewer makes no internet "
                           "connection at all. (The forecast is the only one: the coordinates of the chosen "
                           "Georgian city are sent to api.met.no, nothing else.)"),
        "DisablePrinting": ("Turn off printing",
                            "File \u2192 Print and Ctrl+P are blocked for every document type."),
        "DisableAuditLog": ("Turn off the local audit log",
                            "Monkey Viewer keeps %APPDATA%\\MonkeyViewer\\audit.log (who opened, saved, exported, "
                            "decrypted or verified which file). Enable this policy to stop writing it."),
        "EventLog": ("Write audit events to the Windows event log",
                     "Also writes every audit event to the Application log, source \"MonkeyViewer\" (registered by "
                     "the MSI), so it can be collected centrally (Windows Event Forwarding, SIEM)."),
        "AuditLogPath": ("Additional audit log file",
                         "Also appends audit events (JSON lines) to this file, e.g. "
                         "\\\\server\\audit$\\MonkeyViewer\\%USERNAME%.jsonl. Environment variables are expanded."),
        "AuditFileHashes": ("Record file hashes in the audit log",
                            "Adds the SHA-256 of every opened file to the audit log. Costs some time for very "
                            "large files."),
        "Language": ("Interface language",
                     "Sets the language of Monkey Viewer's interface for everyone and hides the choice in More > "
                     "Language. Not configured: each user chooses; the default follows the Windows display "
                     "language."),
        "Language_ka": "Georgian (ქართული)",
        "Language_en": "English",
        "_path_label": "Path:",
        "_lang_label": "Language:",
    },
    "ka-GE": {
        "_category": "Monkey Viewer",
        "_supported": f"Monkey Viewer {app_info.VERSION.split('.')[0]}.0 და უფრო ახალი",
        "_desc": "Monkey Viewer-ის (სპეციფიური ფაილების მნახველის) პარამეტრები.",
        "DisableAssociationPrompt": ("ფაილის ტიპების შერჩევის ფანჯარა არ გამოჩნდეს",
                                     "პირველ გაშვებაზე Monkey Viewer მომხმარებელს ეკითხება, რომელი ფაილის ტიპები "
                                     "გაიხსნას მასში. ჩართვის შემთხვევაში ეს კითხვა აღარ ჩნდება."),
        "DisableAssociationChanges": ("მომხმარებელმა ვერ შეცვალოს ფაილის ასოციაციები",
                                      "იმალება File associations და Remove all associations. Monkey Viewer "
                                      "ფაილის ტიპების მიბმას არასდროს ცვლის."),
        "DisableExternalTools": ("დამხმარე პროგრამები არ გაეშვას",
                                 "Monkey Viewer არ უშვებს GnuPG-ს, DjVuLibre-ს და ODA File Converter-ს, "
                                 "დაყენებულიც რომ იყოს."),
        "DisableDecryption": ("ფაილები არ გაიშიფროს",
                              "დაშიფრული ფაილები (.enc, .gpg, დაშიფრული .p7m...) იცნობა და აღიწერება, მაგრამ არ "
                              "იშიფრება. ხელმოწერის შემოწმება რჩება."),
        "ReadOnly": ("მხოლოდ ნახვის რეჟიმი",
                     "Monkey Viewer-იდან ვერაფერი შეინახება და ვერ დაექსპორტდება (Save, Save As, Export, PDF "
                     "ხელსაწყოები, რომლებიც ფაილს წერენ)."),
        "DisableWeather": ("ამინდის პროგნოზის გამორთვა",
                           "სტატუსის ზოლში ამინდი აღარ ჩანს და Monkey Viewer ინტერნეტს საერთოდ აღარ უკავშირდება. "
                           "(პროგნოზი ერთადერთი კავშირია: api.met.no-ს ეგზავნება მხოლოდ არჩეული ქალაქის "
                           "კოორდინატები.)"),
        "DisablePrinting": ("ბეჭდვის გამორთვა",
                            "ფაილი \u2192 ბეჭდვა და Ctrl+P იბლოკება ყველა ტიპის დოკუმენტისთვის."),
        "DisableAuditLog": ("ლოკალური აუდიტის ჟურნალის გამორთვა",
                            "Monkey Viewer წერს %APPDATA%\\MonkeyViewer\\audit.log-ს (ვინ რომელი ფაილი გახსნა, შეინახა, "
                            "დააექსპორტა, გაშიფრა ან შეამოწმა). ჩართვისას ჟურნალი აღარ იწერება."),
        "EventLog": ("აუდიტის მოვლენები Windows Event Log-ში",
                     "აუდიტის ყველა მოვლენა იწერება Application ჟურნალშიც (წყარო \"MonkeyViewer\", რეგისტრირდება "
                     "MSI-ით) — ცენტრალიზებული შეგროვებისთვის (Event Forwarding, SIEM)."),
        "AuditLogPath": ("დამატებითი აუდიტის ფაილი",
                         "აუდიტის მოვლენები (JSON lines) დამატებით ამ ფაილშიც ჩაიწერება, მაგ. "
                         "\\\\server\\audit$\\MonkeyViewer\\%USERNAME%.jsonl. გარემოს ცვლადები იხსნება."),
        "AuditFileHashes": ("ფაილების ჰეშები აუდიტის ჟურნალში",
                            "ყოველი გახსნილი ფაილის SHA-256 ჩაიწერება აუდიტის ჟურნალში."),
        "Language": ("ინტერფეისის ენა",
                     "ადგენს Monkey Viewer-ის ინტერფეისის ენას ყველასთვის და მალავს არჩევანს მენიუში „მეტი > ენა“. "
                     "თუ არ არის კონფიგურირებული — თითოეული მომხმარებელი თავად ირჩევს; ნაგულისხმევად "
                     "Windows-ის ენა გამოიყენება."),
        "Language_ka": "ქართული",
        "Language_en": "ინგლისური (English)",
        "_path_label": "გზა:",
        "_lang_label": "ენა:",
    },
}


def admx():
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           f'<policyDefinitions xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
           f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" revision="1.0" schemaVersion="1.0" xmlns="{NS}">',
           '  <policyNamespaces>',
           f'    <target prefix="monkeyviewer" namespace="{app_info.PUBLISHER.title()}.Policies.MonkeyViewer" />',
           '    <using prefix="windows" namespace="Microsoft.Policies.Windows" />',
           '  </policyNamespaces>',
           '  <resources minRequiredRevision="1.0" />',
           '  <supportedOn>', '    <definitions>',
           '      <definition name="SUPPORTED_MonkeyViewer" displayName="$(string.SUPPORTED_MonkeyViewer)" />',
           '    </definitions>', '  </supportedOn>',
           '  <categories>', '    <category name="MonkeyViewer" displayName="$(string.MonkeyViewer)" />', '  </categories>',
           '  <policies>']
    for name, (kind, _desc) in DEFINITIONS.items():
        common = (f'name="{name}" class="Both" displayName="$(string.{name})" explainText="$(string.{name}_Help)" '
                  f'key="{KEY}"')
        if kind == "bool":
            out += [f'    <policy {common} valueName="{name}">',
                    '      <parentCategory ref="MonkeyViewer" />', '      <supportedOn ref="SUPPORTED_MonkeyViewer" />',
                    '      <enabledValue><decimal value="1" /></enabledValue>',
                    '      <disabledValue><decimal value="0" /></disabledValue>', '    </policy>']
        elif kind == "enum":
            items = []
            for value in CHOICES[name]:
                items += [f'          <item displayName="$(string.{name}_{value})">',
                          f'            <value><string>{value}</string></value>', '          </item>']
            out += [f'    <policy {common} presentation="$(presentation.{name})">',
                    '      <parentCategory ref="MonkeyViewer" />', '      <supportedOn ref="SUPPORTED_MonkeyViewer" />',
                    '      <elements>', f'        <enum id="{name}" valueName="{name}" required="true">'] + items + [
                    '        </enum>', '      </elements>', '    </policy>']
        else:
            out += [f'    <policy {common} presentation="$(presentation.{name})">',
                    '      <parentCategory ref="MonkeyViewer" />', '      <supportedOn ref="SUPPORTED_MonkeyViewer" />',
                    '      <elements>', f'        <text id="{name}" valueName="{name}" expandable="true" required="true" />',
                    '      </elements>', '    </policy>']
    out += ['  </policies>', '</policyDefinitions>', '']
    return "\n".join(out)


def adml(lang):
    t = TEXT[lang]
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           f'<policyDefinitionResources xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
           f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" revision="1.0" schemaVersion="1.0" xmlns="{NS}">',
           '  <displayName>Monkey Viewer</displayName>', f'  <description>{escape(t["_desc"])}</description>',
           '  <resources>', '    <stringTable>',
           f'      <string id="MonkeyViewer">{escape(t["_category"])}</string>',
           f'      <string id="SUPPORTED_MonkeyViewer">{escape(t["_supported"])}</string>']
    for name in DEFINITIONS:
        title, help_text = t[name]
        out.append(f'      <string id="{name}">{escape(title)}</string>')
        out.append(f'      <string id="{name}_Help">{escape(help_text)}</string>')
        for value in CHOICES.get(name, ()):
            out.append(f'      <string id="{name}_{value}">{escape(t[f"{name}_{value}"])}</string>')
    out += ['    </stringTable>', '    <presentationTable>']
    for name, (kind, _d) in DEFINITIONS.items():
        if kind == "str":
            out += [f'      <presentation id="{name}">', f'        <textBox refId="{name}">',
                    f'          <label>{escape(t["_path_label"])}</label>', '        </textBox>', '      </presentation>']
        elif kind == "enum":
            out += [f'      <presentation id="{name}">',
                    f'        <dropdownList refId="{name}" noSort="true" defaultItem="0">{escape(t["_lang_label"])}'
                    '</dropdownList>', '      </presentation>']
    out += ['    </presentationTable>', '  </resources>', '</policyDefinitionResources>', '']
    return "\n".join(out)


def main():
    base = os.path.join(ROOT, "deploy", "admx")
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "MonkeyViewer.admx"), "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(admx())
    for lang in TEXT:
        os.makedirs(os.path.join(base, lang), exist_ok=True)
        with open(os.path.join(base, lang, "MonkeyViewer.adml"), "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(adml(lang))
    print("ADMX/ADML written to", base)


if __name__ == "__main__":
    main()
