//go:build windows

package collector

import (
	"context"
	"fmt"
	"log"
	"runtime"
	"time"

	"github.com/go-ole/go-ole"
	"github.com/go-ole/go-ole/oleutil"
	"golang.org/x/sys/windows/registry"

	"tiai/agent/internal/logging"
	"tiai/agent/internal/models"
)

// directoryReadTimeout bounds the ADSI bind. A domain controller that does not
// answer makes the bind hang for as long as the LDAP client feels like — and
// the inventory, of which this is the last step, has a heartbeat to catch.
const directoryReadTimeout = 30 * time.Second

// gpoStateKey is where Group Policy processing caches the computer's own
// distinguished name. Present on every domain-joined poste that has applied a
// GPO at least once — which, for an agent deployed by GPO, is every poste.
// A registry read, no directory round trip, no dependency.
const gpoStateKey = `SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\State\Machine`

// ldapNamespaceCLSID is the ADSI LDAP provider's namespace object
// (IADsOpenDSObject), the entry point for binding to an object by path. By
// CLSID rather than by ProgID: it is what GetObject("LDAP:") resolves to, and
// the ProgID is not registered on every SKU.
var ldapNamespaceCLSID = ole.NewGUID("{228D9A82-C302-11CF-9AA4-00AA004A5691}")

// adsSecureAuthentication is ADS_SECURE_AUTHENTICATION: bind with the calling
// context's credentials — the machine account, since the agent runs as
// LocalSystem — which is exactly the identity allowed to read its own object.
const adsSecureAuthentication = 0x1

// readDirectory reads what the domain says about this computer: its DN from
// the registry, and its "location" attribute from the directory itself.
//
// Never an error, at most a nil block: a workgroup poste, a poste that has
// not processed Group Policy, a domain controller that is unreachable — none
// is worth failing the inventory over. The DN alone is still reported when
// the directory cannot be bound, so a server filing by OU keeps working on a
// poste that is off-site.
func readDirectory(ctx context.Context) *models.DirectoryState {
	if ctx.Err() != nil {
		return nil
	}
	dn := readDistinguishedName()
	if dn == "" {
		logging.Debugf("agent: directory: no distinguished name cached (not domain-joined, or no GPO applied yet)")
		return nil
	}
	location := readADLocation(dn)
	return directoryState(dn, location)
}

// readDistinguishedName returns the computer object's DN as Group Policy
// cached it, or "" when there is none.
func readDistinguishedName() string {
	k, err := registry.OpenKey(registry.LOCAL_MACHINE, gpoStateKey, registry.QUERY_VALUE)
	if err != nil {
		return ""
	}
	defer k.Close()
	v, _, err := k.GetStringValue("Distinguished-Name")
	if err != nil {
		return ""
	}
	return v
}

// readADLocation binds to the computer object through ADSI and reads its
// "location" attribute. "" when unset, or when the bind fails — logged at
// debug: on a poste that is off the domain network this fails every day, and
// a line per day would say nothing new.
//
// On a goroutine of its own, on a locked OS thread with its own COM
// apartment, and bounded by directoryReadTimeout — the same discipline as the
// WMI queries: a COM call has no cancellation, and the only way out of one
// that never returns is to leave it behind.
func readADLocation(dn string) string {
	type result struct {
		value string
		err   error
	}
	done := make(chan result, 1)
	go func() {
		defer func() {
			if r := recover(); r != nil {
				done <- result{err: fmt.Errorf("panic: %v", r)}
			}
		}()
		runtime.LockOSThread()
		defer runtime.UnlockOSThread()
		v, err := bindAndReadLocation(dn)
		done <- result{value: v, err: err}
	}()

	select {
	case r := <-done:
		if r.err != nil {
			logging.Debugf("agent: directory: location attribute of %q not read: %v", dn, r.err)
			return ""
		}
		return r.value
	case <-time.After(directoryReadTimeout):
		log.Printf("agent: directory: the ADSI bind to %q has not returned after %s; "+
			"the OU is reported without the location attribute", dn, directoryReadTimeout)
		return ""
	}
}

// bindAndReadLocation does the COM work: initialise an apartment, open the
// LDAP namespace, bind to the object with the caller's credentials, read one
// attribute. Every interface is released on the way out.
func bindAndReadLocation(dn string) (string, error) {
	if err := ole.CoInitializeEx(0, ole.COINIT_MULTITHREADED); err != nil {
		// S_FALSE (already initialised on this thread) comes back as an error
		// from go-ole; the thread is fresh here, so anything else is real.
		var oleErr *ole.OleError
		if !asOleError(err, &oleErr) || oleErr.Code() != 1 {
			return "", fmt.Errorf("CoInitializeEx: %w", err)
		}
	}
	defer ole.CoUninitialize()

	unknown, err := ole.CreateInstance(ldapNamespaceCLSID, ole.IID_IDispatch)
	if err != nil {
		return "", fmt.Errorf("LDAP namespace: %w", err)
	}
	defer unknown.Release()
	namespace, err := unknown.QueryInterface(ole.IID_IDispatch)
	if err != nil {
		return "", fmt.Errorf("LDAP namespace IDispatch: %w", err)
	}
	defer namespace.Release()

	// A NULL BSTR — not an empty one — for the user name and password is what
	// tells ADSI to bind as the calling thread (vbNullString in VBScript).
	// Go's "" would be an empty string, which ADSI reads as a bind attempt
	// with an empty account; go-ole's nil would be VT_NULL, which the
	// dispatch layer refuses to coerce to a string. A VARIANT built by hand
	// is the one form that carries the NULL through.
	nullString := ole.NewVariant(ole.VT_BSTR, 0)
	bound, err := oleutil.CallMethod(namespace, "OpenDSObject",
		"LDAP://"+dn, &nullString, &nullString, adsSecureAuthentication)
	if err != nil {
		return "", fmt.Errorf("OpenDSObject: %w", err)
	}
	defer bound.Clear()
	object := bound.ToIDispatch()
	if object == nil {
		return "", fmt.Errorf("OpenDSObject returned no object")
	}

	// IADs::Get raises E_ADS_PROPERTY_NOT_FOUND on an attribute the object
	// does not carry, which is the common case: most computer objects have no
	// location typed in. Not distinguished from any other failure — the
	// answer is the same, "no opinion".
	value, err := oleutil.CallMethod(object, "Get", "location")
	if err != nil {
		return "", nil
	}
	defer value.Clear()
	return value.ToString(), nil
}

// asOleError is errors.As without importing errors for one call site.
func asOleError(err error, target **ole.OleError) bool {
	e, ok := err.(*ole.OleError)
	if ok {
		*target = e
	}
	return ok
}
