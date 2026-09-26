internal static class InputGeometry
{
    public static int Normalize(int coordinate, int origin, int extent)
    {
        if (extent <= 0 || coordinate < origin || (long)coordinate >= (long)origin + extent)
            throw new NativeFailure("point_outside_desktop", "Coordinate is outside the virtual desktop.");
        return (int)Math.Clamp((((long)coordinate - origin) * 65536L + 32768L) / extent, 0L, 65535L);
    }
}
