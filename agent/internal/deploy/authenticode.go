package deploy

import (
	"bytes"
	"crypto/x509"
	"encoding/asn1"
	"encoding/binary"
	"errors"
	"io"
	"math/big"
	"os"
)

// SignerName reads the name of the Authenticode signer of a PE file: the
// common name of the certificate that signed it — what the "Signatures
// numériques" tab shows as "Nom du signataire".
//
// Reading is not verifying. The caller verifies the signature with Windows
// (WinVerifyTrust) and only then compares this name with the publishers the
// GPO approved. The signer is found the way Windows finds it: the first
// SignerInfo's issuer and serial number, looked up among the certificates the
// signature carries — not merely "a certificate in the blob", which a
// tampered file could pad with any name it likes.
func SignerName(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	blob, err := pkcs7Blob(f)
	if err != nil {
		return "", err
	}
	cert, err := signerCertificate(blob)
	if err != nil {
		return "", err
	}
	if cert.Subject.CommonName != "" {
		return cert.Subject.CommonName, nil
	}
	return cert.Subject.String(), nil
}

var errNotSigned = errors.New("fichier non signé (pas de signature Authenticode)")

func readAt(r io.ReaderAt, off int64, n int) ([]byte, error) {
	if off < 0 || n < 0 || n > 64<<20 {
		return nil, errNotSigned
	}
	buf := make([]byte, n)
	if _, err := r.ReadAt(buf, off); err != nil {
		return nil, errNotSigned
	}
	return buf, nil
}

// pkcs7Blob returns the PKCS#7 SignedData of the PE's first WIN_CERTIFICATE.
func pkcs7Blob(r io.ReaderAt) ([]byte, error) {
	head, err := readAt(r, 0, 0x40)
	if err != nil || !bytes.Equal(head[:2], []byte("MZ")) {
		return nil, errNotSigned
	}
	pe := int64(binary.LittleEndian.Uint32(head[0x3C:]))
	sig, err := readAt(r, pe, 4)
	if err != nil || !bytes.Equal(sig, []byte("PE\x00\x00")) {
		return nil, errNotSigned
	}
	optional := pe + 24
	magicB, err := readAt(r, optional, 2)
	if err != nil {
		return nil, errNotSigned
	}
	var dirs int64
	switch binary.LittleEndian.Uint16(magicB) {
	case 0x10B:
		dirs = optional + 96
	case 0x20B:
		dirs = optional + 112
	default:
		return nil, errNotSigned
	}
	entry, err := readAt(r, dirs+8*4, 8)
	if err != nil {
		return nil, errNotSigned
	}
	addr := int64(binary.LittleEndian.Uint32(entry))
	size := int64(binary.LittleEndian.Uint32(entry[4:]))
	if addr == 0 || size < 8 {
		return nil, errNotSigned
	}
	wc, err := readAt(r, addr, 8)
	if err != nil {
		return nil, errNotSigned
	}
	length := int64(binary.LittleEndian.Uint32(wc))
	if binary.LittleEndian.Uint16(wc[6:]) != 0x0002 || length <= 8 {
		return nil, errNotSigned
	}
	return readAt(r, addr+8, int(min(length, size)-8))
}

type contentInfo struct {
	ContentType asn1.ObjectIdentifier
	Content     asn1.RawValue `asn1:"explicit,tag:0"`
}

type issuerAndSerial struct {
	Issuer asn1.RawValue
	Serial *big.Int
}

func signerCertificate(blob []byte) (*x509.Certificate, error) {
	bad := errors.New("signature Authenticode illisible")
	var ci contentInfo
	if _, err := asn1.Unmarshal(blob, &ci); err != nil {
		return nil, bad
	}
	// SignedData ::= SEQUENCE { version, digestAlgorithms SET, contentInfo,
	//   [0] IMPLICIT certificates OPTIONAL, [1] crls OPTIONAL, signerInfos SET }
	// Into a RawValue, encoding/asn1 keeps the explicit [0] wrapper: the
	// SignedData SEQUENCE is inside it.
	inner := ci.Content
	if inner.Class == asn1.ClassContextSpecific {
		if _, err := asn1.Unmarshal(inner.Bytes, &inner); err != nil {
			return nil, bad
		}
	}
	if inner.Class != asn1.ClassUniversal || inner.Tag != asn1.TagSequence {
		return nil, bad
	}
	rest := inner.Bytes
	var certs []*x509.Certificate
	var signerInfos asn1.RawValue
	for i := 0; len(rest) > 0; i++ {
		var el asn1.RawValue
		var err error
		if rest, err = asn1.Unmarshal(rest, &el); err != nil {
			return nil, bad
		}
		switch {
		case el.Class == asn1.ClassContextSpecific && el.Tag == 0:
			if certs, err = x509.ParseCertificates(el.Bytes); err != nil {
				return nil, bad
			}
		case el.Class == asn1.ClassUniversal && el.Tag == asn1.TagSet && i > 1:
			signerInfos = el // the last SET: the signer infos
		}
	}
	if len(certs) == 0 || len(signerInfos.Bytes) == 0 {
		return nil, bad
	}
	// The first SignerInfo: SEQUENCE { version, issuerAndSerialNumber, … }.
	var si asn1.RawValue
	if _, err := asn1.Unmarshal(signerInfos.Bytes, &si); err != nil {
		return nil, bad
	}
	var version int
	after, err := asn1.Unmarshal(si.Bytes, &version)
	if err != nil {
		return nil, bad
	}
	var ias issuerAndSerial
	if _, err := asn1.Unmarshal(after, &ias); err != nil {
		return nil, bad
	}
	for _, c := range certs {
		if c.SerialNumber.Cmp(ias.Serial) == 0 && bytes.Equal(c.RawIssuer, ias.Issuer.FullBytes) {
			return c, nil
		}
	}
	return nil, errors.New("certificat du signataire absent de la signature")
}
