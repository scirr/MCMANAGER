namespace MCManager.Client.Tests;

internal sealed class TestProtector : IProfileProtector
{
    public byte[] Protect(byte[] plain) => plain.Select(b => (byte)(b ^ 0x5A)).Reverse().ToArray();

    public byte[] Unprotect(byte[] protectedData) => protectedData.Reverse().Select(b => (byte)(b ^ 0x5A)).ToArray();
}
