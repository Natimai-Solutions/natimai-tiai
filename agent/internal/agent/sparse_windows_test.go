package agent

import (
	"os"

	"golang.org/x/sys/windows"
)

// makeSparse marks f sparse, so that a test growing it to gibibytes with
// Truncate allocates nothing: NTFS, unlike the Linux file systems, would
// otherwise reserve every cluster and fill the CI runner's disk.
func makeSparse(f *os.File) error {
	var returned uint32
	return windows.DeviceIoControl(
		windows.Handle(f.Fd()), windows.FSCTL_SET_SPARSE, nil, 0, nil, 0, &returned, nil,
	)
}
