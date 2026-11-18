package msg

import (
	"fmt"
	"strings"
)

// french writes each code's sentence from its parameters: the text an older
// server stores and shows, and the one the console's French must match
// (frontend/src/i18n/messages/commands.ts). A change of wording here is a
// change there, and of testdata/messages_fr.json (go test ./internal/msg
// -update).
var french = map[string]func(Params) string{
	// --- The agent itself (internal/agent).
	"agent.backlog_full": func(p Params) string {
		return fmt.Sprintf("file d'attente de l'agent pleine (%v commandes) : commande non exécutée, à relancer", p["max"])
	},
	"agent.stopped": func(Params) string {
		return "interrompue par l'arrêt de l'agent avant d'avoir commencé : à relancer"
	},
	"agent.unsupported_type": func(p Params) string {
		return fmt.Sprintf("type de commande %s non pris en charge par l'agent %s : mettez l'agent à jour",
			str(p, "type"), str(p, "version"))
	},
	"agent.power_pending": func(p Params) string {
		return fmt.Sprintf("un %s de ce poste est déjà programmé : commande non exécutée, "+
			"à relancer une fois le poste revenu en ligne", powerNoun(p))
	},

	// --- Restart and shutdown (internal/agent/power.go, collector/system*.go).
	"power.too_soon": func(p Params) string {
		return fmt.Sprintf("opération refusée : un %s a déjà été programmé sur ce poste il y a %s "+
			"(délai minimum %s)", powerNoun(p), str(p, "ago"), str(p, "min"))
	},
	"power.too_soon_boot": func(p Params) string {
		return fmt.Sprintf("opération refusée : ce poste a démarré il y a %s (délai minimum %s avant "+
			"de l'arrêter ou de le redémarrer à nouveau)", str(p, "ago"), str(p, "min"))
	},
	"power.scheduled": func(p Params) string {
		return fmt.Sprintf("%s programmé dans %v secondes.\n", powerLabel(p), p["seconds"])
	},
	"power.schedule_failed": func(p Params) string {
		return fmt.Sprintf("%s : l'opération n'a pas pu être programmée (code %s)",
			powerLabel(p), str(p, "code"))
	},

	// --- Windows Update (internal/agent/wu.go, collector/wu*.go).
	"wu.scan": func(p Params) string {
		return fmt.Sprintf("%v mise(s) à jour en attente.", p["count"])
	},
	"wu.timeout": func(Params) string {
		return "délai d'exécution dépassé pour l'opération Windows Update"
	},
	"wu.interrupted": func(Params) string {
		return "opération Windows Update interrompue (arrêt de l'agent)"
	},
	"wu.known_error": func(p Params) string {
		return fmt.Sprintf("%s (%s)", WUHints[str(p, "hresult")], str(p, "detail"))
	},
	"wu.install_incomplete": func(p Params) string {
		return fmt.Sprintf("%v mise(s) à jour sur %v n'ont pas été installées", p["failed"], p["selected"])
	},
	"wu.install_result": func(p Params) string {
		return fmt.Sprintf("installation %s (code %v)", WUResults[str(p, "result")], p["code"])
	},

	// --- Inventory (internal/agent/inventory.go).
	"inventory.scan": func(p Params) string {
		return fmt.Sprintf("%v disque(s), %v volume(s), %v carte(s) réseau, %v logiciel(s).",
			p["disks"], p["volumes"], p["nics"], p["software"])
	},
	"inventory.scan_without_software": func(p Params) string {
		return fmt.Sprintf("%v disque(s), %v volume(s), %v carte(s) réseau, "+
			"inventaire logiciel désactivé sur ce poste.", p["disks"], p["volumes"], p["nics"])
	},
	"inventory.unavailable": func(Params) string {
		return "inventaire indisponible sur cette plateforme"
	},

	// --- Defender (collector/defender.go).
	"defender.quick_scan.timeout": func(p Params) string {
		return defenderTimeout("l'analyse rapide Defender", p,
			"L'analyse peut se poursuivre sur le poste : vérifier la date de "+
				"dernière analyse rapide avant de la relancer. Un dépassement répété "+
				"signale un moteur Defender bloqué (redémarrer le poste).")
	},
	"defender.full_scan.timeout": func(p Params) string {
		return defenderTimeout("l'analyse complète Defender", p,
			"L'analyse peut se poursuivre sur le poste : vérifier la date de "+
				"dernière analyse complète avant de la relancer. Si les analyses "+
				"complètes de ce parc sont légitimement plus longues (gros disques "+
				"mécaniques), augmenter defender_full_scan_timeout_seconds "+
				"(registre : DefenderFullScanTimeoutSeconds).")
	},
	"defender.signatures.timeout": func(p Params) string {
		return defenderTimeout("la mise à jour des signatures Defender", p,
			"Vérifier que le poste joint sa source de signatures (WSUS, "+
				"Windows Update ou partage de définitions configuré par stratégie).")
	},
	"defender.quick_scan.interrupted": func(Params) string {
		return "l'analyse rapide Defender a été interrompue (arrêt de l'agent) : à relancer"
	},
	"defender.full_scan.interrupted": func(Params) string {
		return "l'analyse complète Defender a été interrompue (arrêt de l'agent) : à relancer"
	},
	"defender.signatures.interrupted": func(Params) string {
		return "la mise à jour des signatures Defender a été interrompue (arrêt de l'agent) : à relancer"
	},

	// --- Maintenance tools (collector/maintenance*.go).
	"maintenance.timeout": func(p Params) string {
		return fmt.Sprintf("délai d'exécution dépassé pour %s", str(p, "exe"))
	},
	"maintenance.interrupted": func(p Params) string {
		return fmt.Sprintf("exécution de %s interrompue (arrêt de l'agent)", str(p, "exe"))
	},
	"maintenance.launch_failed": func(p Params) string {
		return fmt.Sprintf("lancement de %s : %s", str(p, "exe"), str(p, "detail"))
	},
	"maintenance.exit_code": func(p Params) string {
		return fmt.Sprintf("code de retour %s", str(p, "code"))
	},
	"sfc.failed": func(p Params) string {
		return fmt.Sprintf("sfc a terminé en erreur (code %s)", str(p, "code"))
	},
	"sfc.failed_summary": func(p Params) string {
		return fmt.Sprintf("sfc a terminé en erreur (code %s) : %s", str(p, "code"), str(p, "summary"))
	},
	"dism.source_missing": func(p Params) string {
		return fmt.Sprintf("source de réparation inaccessible (%s) : ce poste ne joint ni Windows Update "+
			"ni son serveur WSUS, ou la source de réparation n'y est pas publiée", str(p, "hresult"))
	},
	"dism.failed": func(p Params) string {
		return fmt.Sprintf("dism a terminé en erreur (code %s)", str(p, "code"))
	},
	"chkdsk.failed": func(p Params) string {
		return fmt.Sprintf("chkdsk a terminé avec le code %s", str(p, "code"))
	},
	"chkdsk.offline_repair": func(p Params) string {
		return fmt.Sprintf("chkdsk : %s (code %v) — une réparation hors ligne (chkdsk /spotfix, "+
			"appliquée au redémarrage) est nécessaire", ChkdskMeanings[str(p, "meaning")], p["code"])
	},
	"time.service_stopped": func(p Params) string {
		return fmt.Sprintf("le service de temps Windows (W32Time) est arrêté sur ce poste (%s)",
			str(p, "hresult"))
	},
	"time.failed": func(p Params) string {
		return fmt.Sprintf("la resynchronisation de l'horloge a échoué (code %s)", str(p, "code"))
	},
	"spooler.reset": func(p Params) string {
		return fmt.Sprintf("Spouleur d'impression arrêté.\nFile d'impression purgée (%v fichier(s)).\n"+
			"Spouleur d'impression redémarré.", p["removed"])
	},
	"spooler.stop_failed": func(p Params) string {
		return "arrêt du spouleur : " + str(p, "detail")
	},
	"spooler.start_failed": func(p Params) string {
		return "démarrage du spouleur : " + str(p, "detail")
	},
	"spooler.purge_failed": func(p Params) string {
		return "purge de la file d'impression : " + str(p, "detail")
	},

	// --- Wake-on-LAN relayed by this poste (collector/wol.go).
	"wol.relay.sent": func(p Params) string {
		return fmt.Sprintf("Paquet magique émis vers %s depuis ce poste — %v copie(s) sur %s.\n"+
			"L'émission ne prouve pas le réveil : le protocole n'accuse rien, et le "+
			"poste visé ne réapparaîtra dans la console qu'à la remontée de son agent.",
			str(p, "mac"), p["copies"], str(p, "targets"))
	},
	"wol.relay.no_subnet": func(Params) string {
		return "ce poste n'a aucun sous-réseau IPv4 sur lequel diffuser le paquet magique"
	},
	"wol.relay.nic_failed": func(p Params) string {
		return "lecture des cartes réseau de ce poste : " + str(p, "detail")
	},
	"wol.relay.send_failed": func(p Params) string {
		return "émission du paquet magique impossible : " + str(p, "detail")
	},
	"wol.relay.bad_mac": func(p Params) string {
		return "adresse MAC à réveiller invalide : " + str(p, "mac")
	},

	// --- Software deployment (internal/deploy, internal/agent).
	"deploy.unsupported": func(Params) string {
		return "déploiement logiciel non pris en charge sur ce système"
	},
	"deploy.not_enabled": func(Params) string {
		return "déploiement non activé sur ce poste (aucune clé Deploy* posée par GPO)"
	},
	"deploy.no_package": func(Params) string {
		return "commande sans paquet"
	},
	"deploy.package_id_refused": func(p Params) string {
		return "identifiant de paquet refusé : " + str(p, "id")
	},
	"deploy.bad_manifest": func(Params) string {
		return "manifeste absent ou mal encodé"
	},
	"deploy.no_step": func(p Params) string {
		return "le paquet ne définit pas de " + map[string]string{
			"install": "installation", "uninstall": "désinstallation"}[str(p, "action")]
	},
	"deploy.no_trust_method": func(Params) string {
		return "aucune méthode de confiance pour les paquets de fichiers n'est activée sur ce poste " +
			"(DeploySigners / DeployPublishers)"
	},
	"deploy.unsigned_no_publisher": func(Params) string {
		return "paquet non signé, et aucun éditeur approuvé sur ce poste (DeployPublishers)"
	},
	"deploy.install_removes": func(Params) string {
		return "l'installation de ce paquet lance une désinstallation (msiexec /x, /uninstall ou REMOVE=) : " +
			"refusée — placez cette commande dans la désinstallation du paquet"
	},
	"deploy.method_a.msiexec": func(Params) string {
		return "méthode A : msiexec n'est accepté que pour désinstaller un code produit"
	},
	"deploy.method_a.exe_only": func(Params) string {
		return "méthode A : seul un exécutable (.exe) signé par un éditeur approuvé peut être lancé " +
			"— signez le paquet (méthode B)"
	},
	"deploy.method_a.too_large": func(p Params) string {
		return fmt.Sprintf("méthode A : le manifeste annonce plus de %v Gio à télécharger "+
			"— signez le paquet (méthode B)", p["gib"])
	},
	"deploy.method_a.loadable": func(p Params) string {
		return fmt.Sprintf("méthode A : %s ne peut pas accompagner l'exécutable (fichier que Windows "+
			"pourrait charger ou lancer) — signez le paquet (méthode B)", str(p, "file"))
	},
	"deploy.signature.unsigned": func(Params) string {
		return "paquet non signé"
	},
	"deploy.signature.bad_certificate": func(Params) string {
		return "certificat de signature mal encodé"
	},
	"deploy.signature.untrusted": func(p Params) string {
		return fmt.Sprintf("certificat de signature non approuvé sur ce poste (empreinte %s absente "+
			"de DeploySigners)", str(p, "thumbprint"))
	},
	"deploy.signature.unreadable_certificate": func(p Params) string {
		return "certificat de signature illisible : " + str(p, "detail")
	},
	"deploy.signature.bad_signature": func(Params) string {
		return "signature mal encodée"
	},
	"deploy.signature.algorithm_mismatch": func(Params) string {
		return "algorithme incompatible avec la clé"
	},
	"deploy.signature.invalid": func(Params) string {
		return "signature invalide : le manifeste a changé depuis sa signature"
	},
	"deploy.signature.unsupported_key": func(Params) string {
		return "type de clé non pris en charge"
	},
	"deploy.not_signed": func(Params) string {
		return "fichier non signé (pas de signature Authenticode)"
	},
	"deploy.authenticode_refused": func(p Params) string {
		return fmt.Sprintf("signature de %s refusée par Windows : %s", str(p, "file"), str(p, "detail"))
	},
	"deploy.publisher_not_approved": func(p Params) string {
		return fmt.Sprintf("éditeur %s non approuvé sur ce poste (DeployPublishers)", str(p, "publisher"))
	},
	"deploy.download_failed": func(p Params) string {
		return fmt.Sprintf("téléchargement de %s : %s", str(p, "file"), str(p, "detail"))
	},
	"deploy.launch_failed": func(p Params) string {
		return fmt.Sprintf("lancement de %s : %s", str(p, "file"), str(p, "detail"))
	},
	"deploy.exit_code": func(p Params) string {
		text := fmt.Sprintf("%s a renvoyé le code %v", str(p, "file"), p["code"])
		if note := trustNote(p); note != "" {
			text += " (" + note + ")"
		}
		return text
	},
	"deploy.done": func(p Params) string {
		verb := map[string]string{"install": "Installation", "uninstall": "Désinstallation"}[str(p, "action")]
		what := str(p, "name")
		if what == "" {
			what = "paquet " + str(p, "package_id")
		}
		text := fmt.Sprintf("%s de %s terminée (%s)", verb, what,
			joinNonEmpty(", ", "méthode "+str(p, "method"), trustNote(p)))
		if boolParam(p, "reboot") {
			text += "\nRedémarrage requis pour terminer."
		}
		return text
	},
	"deploy.winget_done": func(p Params) string {
		text := fmt.Sprintf("winget %s %s : terminé", str(p, "action"), str(p, "id"))
		if boolParam(p, "already") {
			text += " (déjà installé, rien à faire)"
		}
		return text
	},
	"deploy.winget_no_match": func(Params) string {
		return "aucun paquet winget ne correspond à cet identifiant"
	},
	"deploy.winget_failed": func(p Params) string {
		return fmt.Sprintf("winget a échoué (code %s)", str(p, "code"))
	},
	"deploy.winget_not_enabled": func(Params) string {
		return "winget non activé sur ce poste (valeur DeployWinget absente ou à 0)"
	},
	"deploy.winget_missing": func(Params) string {
		return "winget absent de ce poste (App Installer non installé — fréquent sur LTSC et " +
			"Windows Server) : utiliser un paquet de fichiers"
	},
	"deploy.winget_refused": func(p Params) string {
		return "identifiant winget refusé : " + str(p, "id")
	},
	"deploy.winget_not_allowed": func(p Params) string {
		return fmt.Sprintf("identifiant winget %s absent de DeployWingetAllow", str(p, "id"))
	},
	"deploy.winget_version_refused": func(p Params) string {
		return "version winget refusée : " + str(p, "version")
	},
}

// WUHints maps the Windows Update result codes an administrator actually
// meets in a managed parc to a sentence that says what to do (wu.known_error).
// Only documented codes are worded: anything else is reported raw.
var WUHints = map[string]string{
	"0x80070422": "le service Windows Update (wuauserv) est désactivé sur ce poste",
	"0x8024402c": "la source de mises à jour est injoignable : le poste ne résout pas le nom de son serveur WSUS (ou de Windows Update)",
	"0x80072ee2": "délai dépassé en joignant la source de mises à jour : réseau, proxy ou serveur WSUS indisponible",
	"0x8024002e": "l'accès à Windows Update est interdit par stratégie : ce poste doit passer par son serveur WSUS",
	"0x80248014": "service de mises à jour inconnu : la configuration WSUS du poste pointe vers un service qui n'existe pas",
	"0x80244022": "le serveur de mises à jour a répondu « service indisponible » (HTTP 503)",
	"0x80240016": "une autre installation est déjà en cours (TrustedInstaller occupé) : réessayer plus tard",
	"0x80240438": "aucune source de mises à jour n'est configurée sur ce poste",
}

// WUResults names a Windows Update operation's result (wu.install_result).
var WUResults = map[string]string{
	"succeeded":             "installée",
	"succeeded_with_errors": "installée avec des erreurs",
	"failed":                "échec",
	"aborted":               "abandonnée",
	"in_progress":           "encore en cours",
	"not_started":           "non démarrée",
}

// ChkdskMeanings names the exit codes Microsoft documents for chkdsk
// (chkdsk.offline_repair).
var ChkdskMeanings = map[string]string{
	"errors_found":   "des erreurs ont été trouvées",
	"partly_checked": "le volume n'a pas pu être entièrement vérifié",
	"not_checked":    "le volume n'a pas pu être vérifié",
}

func str(p Params, key string) string {
	if v, ok := p[key]; ok && v != nil {
		return fmt.Sprint(v)
	}
	return ""
}

func boolParam(p Params, key string) bool {
	v, _ := p[key].(bool)
	return v
}

// powerNoun is the operation inside a sentence (« un redémarrage »).
func powerNoun(p Params) string {
	if str(p, "action") == "shutdown" {
		return "arrêt"
	}
	return "redémarrage"
}

// powerLabel is the operation at the head of a sentence.
func powerLabel(p Params) string {
	if str(p, "action") == "shutdown" {
		return "Arrêt"
	}
	return "Redémarrage"
}

func defenderTimeout(label string, p Params, advice string) string {
	return fmt.Sprintf("délai dépassé : %s ne s'est pas terminée en %s. %s", label, str(p, "budget"), advice)
}

// trustNote says what let a package run: the administrator's signature
// (trust "signer"), or the approved publisher of its executable (trust
// "publisher", with revocation_offline when it could not be checked).
func trustNote(p Params) string {
	switch str(p, "trust") {
	case "signer":
		return "paquet signé par " + str(p, "by")
	case "publisher":
		note := "éditeur approuvé : " + str(p, "by")
		if boolParam(p, "revocation_offline") {
			note += " (révocation non vérifiable hors ligne)"
		}
		return note
	}
	return ""
}

func joinNonEmpty(sep string, parts ...string) string {
	kept := parts[:0:0]
	for _, part := range parts {
		if part = strings.TrimSpace(part); part != "" {
			kept = append(kept, part)
		}
	}
	return strings.Join(kept, sep)
}
