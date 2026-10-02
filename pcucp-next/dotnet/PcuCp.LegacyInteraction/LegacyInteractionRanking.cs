// Same PS5/.NET median-pivot quicksort already qualified for legacy app-profile
// and smart-plan. Equal-key swaps are observable when selecting an action target.
internal static class LegacyInteractionRanking
{
    internal static T[] Sort<T>(IEnumerable<T> input, Comparison<T> compare)
    {
        var values = input.ToArray();
        void Swap(int a, int b) => (values[a], values[b]) = (values[b], values[a]);
        void Median(int a, int b) { if (a != b && compare(values[a], values[b]) > 0) Swap(a, b); }
        void QuickSort(int begin, int end)
        {
            while (begin < end)
            {
                int middle = begin + (end - begin) / 2; Median(begin, middle); Median(begin, end); Median(middle, end);
                T pivot = values[middle]; int a = begin, b = end;
                while (a <= b)
                {
                    while (compare(values[a], pivot) < 0) a++;
                    while (compare(values[b], pivot) > 0) b--;
                    if (a > b) break; Swap(a++, b--);
                }
                if (b - begin <= end - a) { if (begin < b) QuickSort(begin, b); begin = a; }
                else { if (a < end) QuickSort(a, end); end = b; }
            }
        }
        if (values.Length > 1) QuickSort(0, values.Length - 1);
        return values;
    }
}
