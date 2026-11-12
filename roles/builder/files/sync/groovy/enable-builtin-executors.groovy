
import hudson.model.*
import jenkins.model.*

Integer numberOfExecutors = 2
String labelString = "admin"
Node.Mode mode = hudson.model.Node.Mode.EXCLUSIVE

Jenkins jenkins = Jenkins.getInstance()

Boolean doit = false

Integer n = jenkins.getNumExecutors()
if (n != numberOfExecutors) doit = true

String s = jenkins.getLabelString()
if (s != labelString) doit = true

Node.Mode m = jenkins.getMode()
if (m != mode) doit = true

if (doit) {
    jenkins.setNumExecutors(numberOfExecutors)
    jenkins.setLabelString(labelString)
    jenkins.setMode(mode)
    jenkins.save()
    
    println("changed")
} else {
    println("ok")
}
