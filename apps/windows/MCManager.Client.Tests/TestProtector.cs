namespace MCManager.Client.Tests;

internal sealed class TestProtector : IProfileProtector
{
    public byte[] Protect(byte[] plain) => plain.Select(b => (byte)(b ^ 0x5A)).ToArray();

    public byte[] Unprotect(byte[] protectedData) => Protect(protectedData);
}
