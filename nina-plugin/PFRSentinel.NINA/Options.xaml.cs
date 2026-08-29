using System.ComponentModel.Composition;
using System.Windows;

namespace PFRSentinel.NINA {

    [Export(typeof(ResourceDictionary))]
    partial class Options : ResourceDictionary {

        public Options() {
            InitializeComponent();
        }
    }
}
