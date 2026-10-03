using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace PcuCp.LegacyHelper
{
    // Retained only by serve-direct. Default serve/automatic paths are unchanged.
    internal sealed class LegacyHelperDirectLockDirectory : IDisposable
    {
        private readonly List<SafeFileHandle> handles = new List<SafeFileHandle>();
        public string LockPath { get; private set; }
        public LegacyHelperDirectLockDirectory(string path)
        {
            try
            {
                string[] supplied = LegacyHelperDirect.LockPathParts(path);
                string root = path.Substring(0, 3);
                LockPath = Path.GetFullPath(path);
                string[] expanded = LegacyHelperDirect.LockPathParts(LockPath);
                if (!String.Equals(root, LockPath.Substring(0, 3), StringComparison.OrdinalIgnoreCase) ||
                    supplied.Length != expanded.Length ||
                    !String.Equals(supplied[supplied.Length - 1], expanded[expanded.Length - 1], StringComparison.Ordinal))
                    throw new ArgumentException("direct lock path must preserve its root, depth and file leaf");
                if (GetDriveTypeW(root) != 3) throw new ArgumentException("direct lock requires local fixed NTFS");
                Retain(root);
                string originalDirectory = root, expandedDirectory = root;
                for (int i = 0; i < supplied.Length - 1; i++)
                {
                    originalDirectory += (i == 0 ? "" : "\\") + supplied[i];
                    expandedDirectory += (i == 0 ? "" : "\\") + expanded[i];
                    FileIdentity original = Retain(originalDirectory);
                    if (!String.Equals(originalDirectory, expandedDirectory, StringComparison.Ordinal))
                    {
                        FileIdentity canonical = Retain(expandedDirectory);
                        if (original.VolumeSerial != canonical.VolumeSerial || original.IndexHigh != canonical.IndexHigh || original.IndexLow != canonical.IndexLow)
                            throw new IOException("direct lock directory alias must identify the same retained object");
                    }
                }
            }
            catch { Dispose(); throw; }
        }
        private FileIdentity Retain(string directory)
        {
            var handle = CreateFileW(directory, 0x80000000u, 1, IntPtr.Zero, 3, 0x02000000u | 0x00200000u, IntPtr.Zero);
            if (handle.IsInvalid) { handle.Dispose(); throw new IOException("direct lock directory could not be retained"); }
            handles.Add(handle);
            FileIdentity identity;
            if (!GetFileInformationByHandle(handle, out identity) || (identity.Attributes & 0x10) == 0 || (identity.Attributes & 0x400) != 0)
                throw new IOException("direct lock directory must exist without reparse components");
            var fileSystem = new StringBuilder(32);
            if (!GetVolumeInformationByHandleW(handle, null, 0, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, fileSystem, fileSystem.Capacity) ||
                !String.Equals(fileSystem.ToString(), "NTFS", StringComparison.Ordinal))
                throw new IOException("direct lock directory requires NTFS");
            return identity;
        }
        public void Dispose()
        {
            for (int i = handles.Count - 1; i >= 0; i--) handles[i].Dispose();
            handles.Clear();
        }
        [StructLayout(LayoutKind.Sequential)] private struct FileIdentity
        {
            public uint Attributes; public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime, AccessTime, WriteTime;
            public uint VolumeSerial, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetFileInformationByHandle(SafeFileHandle file, out FileIdentity information);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] private static extern uint GetDriveTypeW(string root);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetVolumeInformationByHandleW(SafeFileHandle file, StringBuilder volume, int volumeSize,
            IntPtr serial, IntPtr maxComponent, IntPtr flags, StringBuilder filesystem, int filesystemSize);
    }
}
