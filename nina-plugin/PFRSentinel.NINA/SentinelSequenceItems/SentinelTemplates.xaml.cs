using System.ComponentModel.Composition;
using System.Windows;

namespace PFRSentinel.NINA.SentinelSequenceItems {

    [Export(typeof(ResourceDictionary))]
    public partial class SentinelTemplates : ResourceDictionary {

        public SentinelTemplates() {
            InitializeComponent();
        }
    }
}
