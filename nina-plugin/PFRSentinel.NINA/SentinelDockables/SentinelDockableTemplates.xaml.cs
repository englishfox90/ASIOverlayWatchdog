using System.ComponentModel.Composition;
using System.Windows;

namespace PFRSentinel.NINA.SentinelDockables {

    [Export(typeof(ResourceDictionary))]
    public partial class SentinelDockableTemplates : ResourceDictionary {

        public SentinelDockableTemplates() {
            InitializeComponent();
        }
    }
}
